#!/usr/bin/env python3
"""Build docs/events.json from public Music Mile venue listings."""
from __future__ import annotations

import calendar, hashlib, json, re, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests, yaml
from bs4 import BeautifulSoup
from dateutil import parser as dates

ROOT = Path(__file__).parent
TZ = ZoneInfo("America/Edmonton")
HEADERS = {"User-Agent": "MusicMileCalendar/1.0 (community calendar; weekly fetch)"}
DATE_RX = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?(?:day)?[,. ]*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d{2})?\b", re.I)
TIME_RX = re.compile(r"\b(1[0-2]|0?[1-9]):([0-5]\d)\s*([ap])\.?m\.?")
STAGEHAND_API = "https://api.stagehand.app/api"

def clean(s): return re.sub(r"\s+", " ", s or "").strip()

def iso_date(text):
    text = re.sub(r"(\d)(st|nd|rd|th)", r"\1", text, flags=re.I)
    try:
        d = dates.parse(text, fuzzy=True, default=datetime.now(TZ).replace(hour=19, minute=0, second=0, microsecond=0))
        if not d.tzinfo: d = d.replace(tzinfo=TZ)
        if d.year < datetime.now(TZ).year: d = d.replace(year=datetime.now(TZ).year)
        return d.isoformat()
    except (ValueError, OverflowError): return None

def event(name, venue, start, url, description="", end=None):
    key = hashlib.sha1(f"{venue}|{name}|{start}".lower().encode()).hexdigest()[:16]
    result={"id": key, "title": clean(name), "venue": venue, "start": start,
            "url": url, "description": clean(description)[:500]}
    if end: result["end"]=end
    return result

def parse_local(date_text, time_text="7:00 pm"):
    """Parse a venue's Calgary-local date and time into a timezone-aware ISO value."""
    year_match=re.search(r"\b(20\d{2})\b",date_text)
    year=int(year_match.group(1)) if year_match else datetime.now(TZ).year
    d=dates.parse(f"{date_text} {time_text}",fuzzy=True,default=datetime(year,1,1))
    if d.tzinfo is None: d=d.replace(tzinfo=TZ)
    return d

def times_in(text):
    """Return performance times; prefer show/start time over an earlier doors time."""
    text=clean(text).lower()
    clock=r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)"
    show=re.search(r"(?:show|start(?: time)?)[^\d]{0,12}("+clock+r")",text,re.I)
    if show: return [show.group(1)]
    return [m.group(0) for m in re.finditer(r"\b"+clock,text,re.I)] or ["7:00 pm"]

def jsonld_events(soup, venue, url):
    out=[]
    def walk(x):
        if isinstance(x, list):
            for y in x: yield from walk(y)
        elif isinstance(x, dict):
            if x.get("@type") in ("Event", ["Event"]): yield x
            for y in x.values(): yield from walk(y)
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            for x in walk(json.loads(tag.string or "")):
                if x.get("name") and x.get("startDate"):
                    out.append(event(x["name"],venue,x["startDate"],x.get("url",url),x.get("description","")))
        except (json.JSONDecodeError, TypeError): pass
    return out

def dated_cards(soup, venue, url):
    """Conservative fallback: find small DOM cards containing a date + heading."""
    out=[]
    for heading in soup.select("h2,h3,h4,h5"):
        box=heading
        for _ in range(3):
            if box.parent: box=box.parent
        text=clean(box.get_text(" "))[:1200]
        m=DATE_RX.search(text)
        if not m: continue
        start=iso_date(m.group(0) + (" " + TIME_RX.search(text).group(0) if TIME_RX.search(text) else ""))
        title=clean(heading.get_text(" "))
        if start and 2 < len(title) < 160 and title.lower() not in ("events","what's on","upcoming events"):
            link=heading.find("a",href=True) or box.find("a",href=True)
            out.append(event(title,venue,start,link["href"] if link else url,text))
    return out

def scrape_king_eddy(source):
    soup=fetch_soup(source["url"]); out=[]
    for card in soup.select(".whats-on-date"):
        box=card.parent; title=box.select_one("h3 a[href]")
        if not title: continue
        date_text=clean(card.get_text(" "))
        info=clean((box.select_one(".whats-on-price") or box).get_text(" "))
        for tm in times_in(info)[:1]:
            start=parse_local(date_text,tm).isoformat()
            out.append(event(title.get_text(" "),source["name"],start,title["href"],info))
    return out

def scrape_studio_bell(source):
    soup=fetch_soup(source["url"]); out=[]
    for card in soup.select(".card"):
        date_el=card.select_one(".eventdate"); title=card.select_one(".eventinfo .title a[href]")
        if not date_el or not title: continue
        date_text=clean(date_el.get_text(" "))
        time_text=clean((card.select_one(".eventdetails .time") or card).get_text(" "))
        desc=card.select_one(".description")
        parsed_times=times_in(time_text)
        is_range=bool(re.search(r"\b(?:to|until|through)\b",time_text,re.I)) and len(parsed_times)>1
        # "12 pm and 1:30 pm" means two performances; "10:30 am to 4:30 pm" is one range.
        for tm in parsed_times[:1] if is_range else parsed_times:
            start=parse_local(date_text,tm).isoformat()
            end=parse_local(date_text,parsed_times[1]).isoformat() if is_range else None
            out.append(event(title.get_text(" "),source["name"],start,title["href"],desc.get_text(" ") if desc else time_text,end))
    return out

def scrape_stagehand(source, venue_id):
    now=datetime.now(TZ)
    filt={"where":{"and":[{"venueId":venue_id},{"datetime":{"gte":now.isoformat()}},{"state":{"neq":"cancelled"}}]},
          "order":"datetime ASC","include":["artist",{"relation":"stage","scope":{"fields":["displayName"]}}],"limit":200}
    r=requests.get(f"{STAGEHAND_API}/events",params={"filter":json.dumps(filt,separators=(",",":"))},headers=HEADERS,timeout=35)
    r.raise_for_status(); out=[]
    for x in r.json():
        title=x.get("artistTitle") or (x.get("artist") or {}).get("name") or x.get("venueTitle") or "Live event"
        start=x.get("absStart") or x.get("datetime")
        end=x.get("absEnd") or x.get("eventEnd")
        if not start: continue
        link=x.get("ticketingUrl") or f"https://www.stagehand.app/events/{x['id']}"
        desc=" — ".join(filter(None,[x.get("description"),x.get("coverChargeStr")]))
        out.append(event(title,source["name"],dates.isoparse(start).astimezone(TZ).isoformat(),link,desc,
                         dates.isoparse(end).astimezone(TZ).isoformat() if end else None))
    return out

def nth_weekday(year,month,weekday,n):
    first=datetime(year,month,1,tzinfo=TZ)
    return first+timedelta(days=(weekday-first.weekday())%7+7*(n-1))

def scrape_attic(source):
    """Generate only recurring series explicitly published on The Attic's events page."""
    soup=fetch_soup(source["url"]); text=soup.get_text(" ",strip=True).lower()
    rules=[]
    if "weekly series" in text and "jazz & soul" in text: rules.append(("Jazz & Soul at The Attic",3,"19:30","weekly"))
    if "sundays at 7:30pm" in text: rules.append(("Laugh Loft Stand-Up Comedy",6,"19:30","weekly"))
    if "every saturday" in text: rules.append(("Carly's Angels Drag Show",5,"20:00","weekly_no_august"))
    if "first sunday of every month" in text: rules.append(("Morning Glory Burlesque Brunch",6,"12:00","first"))
    if "3rd sunday" in text or "third sunday" in text: rules.append(("Devilled Legs Drag Brunch",6,"11:45","third"))
    if "last friday" in text: rules.append(("Leopard Lounge Sketch Comedy",4,"20:30","last"))
    now=datetime.now(TZ); horizon=now+timedelta(days=120); out=[]
    day=now.replace(hour=0,minute=0,second=0,microsecond=0)
    while day<=horizon:
        for title,weekday,hm,kind in rules:
            matches=day.weekday()==weekday
            if kind=="first": matches=matches and day.day<=7
            elif kind=="third": matches=matches and 15<=day.day<=21
            elif kind=="last": matches=matches and day.day+7>calendar.monthrange(day.year,day.month)[1]
            elif kind=="weekly_no_august": matches=matches and day.month!=8
            if matches:
                hour,minute=map(int,hm.split(":")); start=day.replace(hour=hour,minute=minute)
                if start>=now: out.append(event(title,source["name"],start.isoformat(),source["url"],"Recurring series published by The Attic; confirm details before attending."))
        day+=timedelta(days=1)
    return out

def parse_festival_hall_soup(soup, source):
    """Accept a Folk Fest card only when its dedicated venue field is exactly Festival Hall."""
    out=[]; now=datetime.now(TZ)
    for card in soup.select(".event-full-item"):
        fields=card.select(".event-feature-info > span")
        if len(fields)<3: continue
        date_text,time_text,venue_text=(clean(x.get_text(" ")) for x in fields[:3])
        if venue_text.casefold() != "festival hall": continue
        title_el=card.select_one(".event-info .headline-6")
        link_el=card.select_one("a.event-link[href], .ctas a[href]")
        if not title_el: continue
        start=parse_local(date_text,time_text)
        # A January listing viewed late in the prior year belongs to the next year.
        if start < now-timedelta(days=60): start=start.replace(year=start.year+1)
        out.append(event(title_el.get_text(" "),source["name"],start.isoformat(),
                         link_el["href"] if link_el else source["url"],f"Venue: {venue_text}"))
    return out

def scrape_festival_hall(source):
    return parse_festival_hall_soup(fetch_soup(source["url"]),source)

def fetch_soup(url):
    r=requests.get(url,headers=HEADERS,timeout=35); r.raise_for_status()
    return BeautifulSoup(r.text,"html.parser")

def scrape_one(source):
    dedicated={"king_eddy":scrape_king_eddy,"studio_bell":scrape_studio_bell,"attic":scrape_attic,
               "festival_hall":scrape_festival_hall,
               "ironwood":lambda s:scrape_stagehand(s,28),"gravity":lambda s:scrape_stagehand(s,1)}
    if source.get("parser") in dedicated:
        return dedicated[source["parser"]](source)
    soup=fetch_soup(source["url"])
    found=jsonld_events(soup,source["name"],source["url"])
    if not found: found=dated_cards(soup,source["name"],source["url"])
    unique={x["id"]:x for x in found}
    return list(unique.values())

def valid_future(x, now):
    """Reject malformed, stale, or implausibly distant events before publishing."""
    try:
        start=dates.isoparse(x["start"])
        if start.tzinfo is None: return False
        end=dates.isoparse(x.get("end",x["start"]))
        if end.tzinfo is None: return False
        return end>=now and start<=now+timedelta(days=730) and end>=start
    except (ValueError,TypeError,KeyError): return False

def main():
    cfg=yaml.safe_load((ROOT/"config/venues.yml").read_text())
    events=[]; status=[]
    for source in cfg["venues"]:
        try:
            got=scrape_one(source); events.extend(got)
            status.append({"venue":source["name"],"ok":True,"events":len(got),"url":source["url"]})
            print(f"OK {source['name']}: {len(got)}")
        except Exception as exc:
            status.append({"venue":source["name"],"ok":False,"events":0,"url":source["url"],"error":str(exc)[:180]})
            print(f"WARN {source['name']}: {exc}",file=sys.stderr)
    now=datetime.now(TZ)
    events={x["id"]:x for x in events if valid_future(x,now)}
    payload={"generatedAt":datetime.now(TZ).isoformat(),"events":sorted(events.values(),key=lambda x:x["start"]),"sources":status}
    (ROOT/"docs").mkdir(exist_ok=True)
    (ROOT/"docs/events.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n")
    if not events: raise SystemExit("No events were extracted; refusing to publish an empty calendar")

if __name__=="__main__": main()

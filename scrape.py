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
HEADERS = {
    "User-Agent": "MusicMileCalendar/1.0 (community calendar; weekly fetch)"
}
DATE_RX = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?(?:day)?[,. ]*"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?"
    r"(?:,?\s+20\d{2})?\b",
    re.I,
)
TIME_RX = re.compile(
    r"\b(1[0-2]|0?[1-9]):([0-5]\d)\s*([ap])\.?m\.?"
)
STAGEHAND_API = "https://api.stagehand.app/api"


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def iso_date(text):
    text = re.sub(r"(\d)(st|nd|rd|th)", r"\1", text, flags=re.I)
    try:
        d = dates.parse(
            text,
            fuzzy=True,
            default=datetime.now(TZ).replace(
                hour=19,
                minute=0,
                second=0,
                microsecond=0,
            ),
        )
        if not d.tzinfo:
            d = d.replace(tzinfo=TZ)
        if d.year < datetime.now(TZ).year:
            d = d.replace(year=datetime.now(TZ).year)
        return d.isoformat()
    except (ValueError, OverflowError):
        return None


def event(name, venue, start, url, description="", end=None):
    key = hashlib.sha1(
        f"{venue}|{name}|{start}".lower().encode()
    ).hexdigest()[:16]

    result = {
        "id": key,
        "title": clean(name),
        "venue": venue,
        "start": start,
        "url": url,
        "description": clean(description)[:500],
    }

    if end:
        result["end"] = end

    return result


def parse_local(date_text, time_text="7:00 pm"):
    """Parse a Calgary-local date and time into a timezone-aware value."""
    year_match = re.search(r"\b(20\d{2})\b", date_text)
    year = (
        int(year_match.group(1))
        if year_match
        else datetime.now(TZ).year
    )

    d = dates.parse(
        f"{date_text} {time_text}",
        fuzzy=True,
        default=datetime(year, 1, 1),
    )

    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)

    return d


def times_in(text):
    """Return event times, preferring show time over doors time."""
    text = clean(text).lower()
    clock = r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)"

    show = re.search(
        r"(?:show|start(?: time)?)[^\d]{0,12}(" + clock + r")",
        text,
        re.I,
    )

    if show:
        return [show.group(1)]

    return [
        match.group(0)
        for match in re.finditer(r"\b" + clock, text, re.I)
    ] or ["7:00 pm"]


def jsonld_events(soup, venue, url):
    out = []

    def walk(value):
        if isinstance(value, list):
            for item in value:
                yield from walk(item)

        elif isinstance(value, dict):
            if value.get("@type") in ("Event", ["Event"]):
                yield value

            for item in value.values():
                yield from walk(item)

    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            for item in walk(json.loads(tag.string or "")):
                if item.get("name") and item.get("startDate"):
                    out.append(
                        event(
                            item["name"],
                            venue,
                            item["startDate"],
                            item.get("url", url),
                            item.get("description", ""),
                        )
                    )
        except (json.JSONDecodeError, TypeError):
            pass

    return out


def dated_cards(soup, venue, url):
    """Find small HTML cards containing a recognizable date and heading."""
    out = []

    for heading in soup.select("h2,h3,h4,h5"):
        box = heading

        for _ in range(3):
            if box.parent:
                box = box.parent

        text = clean(box.get_text(" "))[:1200]
        match = DATE_RX.search(text)

        if not match:
            continue

        time_match = TIME_RX.search(text)
        date_and_time = match.group(0)

        if time_match:
            date_and_time += " " + time_match.group(0)

        start = iso_date(date_and_time)
        title = clean(heading.get_text(" "))

        excluded_titles = (
            "events",
            "what's on",
            "upcoming events",
        )

        if (
            start
            and 2 < len(title) < 160
            and title.lower() not in excluded_titles
        ):
            link = (
                heading.find("a", href=True)
                or box.find("a", href=True)
            )

            out.append(
                event(
                    title,
                    venue,
                    start,
                    link["href"] if link else url,
                    text,
                )
            )

    return out


def scrape_king_eddy(source):
    soup = fetch_soup(source["url"])
    out = []

    for date_element in soup.select(".whats-on-date"):
        box = date_element.parent
        title = box.select_one("h3 a[href]")

        if not title:
            continue

        date_text = clean(date_element.get_text(" "))
        price_element = box.select_one(".whats-on-price")
        info = clean(
            (price_element or box).get_text(" ")
        )

        for event_time in times_in(info)[:1]:
            start = parse_local(
                date_text,
                event_time,
            ).isoformat()

            out.append(
                event(
                    title.get_text(" "),
                    source["name"],
                    start,
                    title["href"],
                    info,
                )
            )

    return out


def scrape_studio_bell(source):
    soup = fetch_soup(source["url"])
    out = []

    for card in soup.select(".card"):
        date_element = card.select_one(".eventdate")
        title = card.select_one(
            ".eventinfo .title a[href]"
        )

        if not date_element or not title:
            continue

        date_text = clean(date_element.get_text(" "))
        time_element = card.select_one(
            ".eventdetails .time"
        )
        time_text = clean(
            (time_element or card).get_text(" ")
        )
        description = card.select_one(".description")
        parsed_times = times_in(time_text)

        is_range = (
            bool(
                re.search(
                    r"\b(?:to|until|through)\b",
                    time_text,
                    re.I,
                )
            )
            and len(parsed_times) > 1
        )

        # "12 pm and 1:30 pm" means two performances.
        # "10:30 am to 4:30 pm" means one time range.
        event_times = (
            parsed_times[:1]
            if is_range
            else parsed_times
        )

        for event_time in event_times:
            start = parse_local(
                date_text,
                event_time,
            ).isoformat()

            end = (
                parse_local(
                    date_text,
                    parsed_times[1],
                ).isoformat()
                if is_range
                else None
            )

            out.append(
                event(
                    title.get_text(" "),
                    source["name"],
                    start,
                    title["href"],
                    (
                        description.get_text(" ")
                        if description
                        else time_text
                    ),
                    end,
                )
            )

    return out


def scrape_stagehand(source, venue_id):
    now = datetime.now(TZ)

    event_filter = {
        "where": {
            "and": [
                {"venueId": venue_id},
                {"datetime": {"gte": now.isoformat()}},
                {"state": {"neq": "cancelled"}},
            ]
        },
        "order": "datetime ASC",
        "include": [
            "artist",
            {
                "relation": "stage",
                "scope": {
                    "fields": ["displayName"]
                },
            },
        ],
        "limit": 200,
    }

    response = requests.get(
        f"{STAGEHAND_API}/events",
        params={
            "filter": json.dumps(
                event_filter,
                separators=(",", ":"),
            )
        },
        headers=HEADERS,
        timeout=35,
    )
    response.raise_for_status()

    out = []

    for item in response.json():
        title = (
            item.get("artistTitle")
            or (item.get("artist") or {}).get("name")
            or item.get("venueTitle")
            or "Live event"
        )

        start = (
            item.get("absStart")
            or item.get("datetime")
        )
        end = (
            item.get("absEnd")
            or item.get("eventEnd")
        )

        if not start:
            continue

        link = (
            item.get("ticketingUrl")
            or f"https://www.stagehand.app/events/{item['id']}"
        )

        description = " — ".join(
            filter(
                None,
                [
                    item.get("description"),
                    item.get("coverChargeStr"),
                ],
            )
        )

        start_local = (
            dates.isoparse(start)
            .astimezone(TZ)
            .isoformat()
        )

        end_local = (
            dates.isoparse(end)
            .astimezone(TZ)
            .isoformat()
            if end
            else None
        )

        out.append(
            event(
                title,
                source["name"],
                start_local,
                link,
                description,
                end_local,
            )
        )

    return out


def nth_weekday(year, month, weekday, occurrence):
    first = datetime(
        year,
        month,
        1,
        tzinfo=TZ,
    )

    return first + timedelta(
        days=(
            (weekday - first.weekday()) % 7
            + 7 * (occurrence - 1)
        )
    )


def scrape_attic(source):
    """Generate recurring events explicitly published by The Attic."""
    soup = fetch_soup(source["url"])
    page_text = soup.get_text(
        " ",
        strip=True,
    ).lower()

    rules = []

    if (
        "weekly series" in page_text
        and "jazz & soul" in page_text
    ):
        rules.append(
            (
                "Jazz & Soul at The Attic",
                3,
                "19:30",
                "weekly",
            )
        )

    if "sundays at 7:30pm" in page_text:
        rules.append(
            (
                "Laugh Loft Stand-Up Comedy",
                6,
                "19:30",
                "weekly",
            )
        )

    if "every saturday" in page_text:
        rules.append(
            (
                "Carly's Angels Drag Show",
                5,
                "20:00",
                "weekly_no_august",
            )
        )

    if "first sunday of every month" in page_text:
        rules.append(
            (
                "Morning Glory Burlesque Brunch",
                6,
                "12:00",
                "first",
            )
        )

    if (
        "3rd sunday" in page_text
        or "third sunday" in page_text
    ):
        rules.append(
            (
                "Devilled Legs Drag Brunch",
                6,
                "11:45",
                "third",
            )
        )

    if "last friday" in page_text:
        rules.append(
            (
                "Leopard Lounge Sketch Comedy",
                4,
                "20:30",
                "last",
            )
        )

    now = datetime.now(TZ)
    horizon = now + timedelta(days=120)
    out = []

    day = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    while day <= horizon:
        for title, weekday, time_value, kind in rules:
            matches = day.weekday() == weekday

            if kind == "first":
                matches = matches and day.day <= 7

            elif kind == "third":
                matches = (
                    matches
                    and 15 <= day.day <= 21
                )

            elif kind == "last":
                days_in_month = calendar.monthrange(
                    day.year,
                    day.month,
                )[1]
                matches = (
                    matches
                    and day.day + 7 > days_in_month
                )

            elif kind == "weekly_no_august":
                matches = (
                    matches
                    and day.month != 8
                )

            if matches:
                hour, minute = map(
                    int,
                    time_value.split(":"),
                )

                start = day.replace(
                    hour=hour,
                    minute=minute,
                )

                if start >= now:
                    out.append(
                        event(
                            title,
                            source["name"],
                            start.isoformat(),
                            source["url"],
                            (
                                "Recurring series published by "
                                "The Attic; confirm details "
                                "before attending."
                            ),
                        )
                    )

        day += timedelta(days=1)

    return out


def parse_festival_hall_soup(soup, source):
    """
    Include a Calgary Folk Fest event only when its venue field
    is exactly 'Festival Hall'.
    """
    out = []
    now = datetime.now(TZ)

    for card in soup.select(".event-full-item"):
        fields = card.select(
            ".event-feature-info > span"
        )

        if len(fields) < 3:
            continue

        date_text, time_text, venue_text = (
            clean(field.get_text(" "))
            for field in fields[:3]
        )

        if venue_text.casefold() != "festival hall":
            continue

        title_element = card.select_one(
            ".event-info .headline-6"
        )
        link_element = card.select_one(
            "a.event-link[href], .ctas a[href]"
        )

        if not title_element:
            continue

        start = parse_local(
            date_text,
            time_text,
        )

        # A January listing viewed late in the prior year
        # belongs to the following calendar year.
        if start < now - timedelta(days=60):
            start = start.replace(
                year=start.year + 1
            )

        out.append(
            event(
                title_element.get_text(" "),
                source["name"],
                start.isoformat(),
                (
                    link_element["href"]
                    if link_element
                    else source["url"]
                ),
                f"Venue: {venue_text}",
            )
        )

    return out


def scrape_festival_hall(source):
    soup = fetch_soup(source["url"])
    return parse_festival_hall_soup(
        soup,
        source,
    )


def parse_offcut_soup(soup, source):
    """
    Create future events from Offcut's explicitly published
    Thursday 7–9 p.m. live-music series.
    """
    page_text = clean(soup.get_text(" "))

    schedule_pattern = (
        r"Thursdays?\s+7\s*"
        r"(?:-|–|to)\s*9\s*p\.?m\.?"
    )

    if not re.search(
        schedule_pattern,
        page_text,
        re.I,
    ):
        return []

    now = datetime.now(TZ)
    horizon = now + timedelta(days=120)
    out = []

    day = now.replace(
        hour=19,
        minute=0,
        second=0,
        microsecond=0,
    )

    # Python weekday number 3 is Thursday.
    while day.weekday() != 3:
        day += timedelta(days=1)

    while day <= horizon:
        if day >= now:
            out.append(
                event(
                    "Thursday Live Music",
                    source["name"],
                    day.isoformat(),
                    source["url"],
                    (
                        "No cover. Recurring Thursday live "
                        "music; confirm details before attending."
                    ),
                    day.replace(hour=21).isoformat(),
                )
            )

        day += timedelta(days=7)

    return out


def scrape_offcut(source):
    soup = fetch_soup(source["url"])
    return parse_offcut_soup(
        soup,
        source,
    )


def fetch_soup(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=35,
    )
    response.raise_for_status()

    return BeautifulSoup(
        response.text,
        "html.parser",
    )


def scrape_one(source):
    dedicated = {
        "king_eddy": scrape_king_eddy,
        "studio_bell": scrape_studio_bell,
        "attic": scrape_attic,
        "festival_hall": scrape_festival_hall,
        "offcut": scrape_offcut,
        "ironwood": lambda item: scrape_stagehand(
            item,
            28,
        ),
        "gravity": lambda item: scrape_stagehand(
            item,
            1,
        ),
    }

    if source.get("parser") in dedicated:
        return dedicated[source["parser"]](source)

    soup = fetch_soup(source["url"])

    found = jsonld_events(
        soup,
        source["name"],
        source["url"],
    )

    if not found:
        found = dated_cards(
            soup,
            source["name"],
            source["url"],
        )

    unique = {
        item["id"]: item
        for item in found
    }

    return list(unique.values())


def valid_future(item, now):
    """
    Reject malformed, past, timezone-less, or implausibly
    distant events before publication.
    """
    try:
        start = dates.isoparse(
            item["start"]
        )

        if start.tzinfo is None:
            return False

        end = dates.isoparse(
            item.get(
                "end",
                item["start"],
            )
        )

        if end.tzinfo is None:
            return False

        return (
            end >= now
            and start <= now + timedelta(days=730)
            and end >= start
        )

    except (
        ValueError,
        TypeError,
        KeyError,
    ):
        return False


def main():
    config = yaml.safe_load(
        (ROOT / "config/venues.yml").read_text()
    )

    events = []
    status = []

    for source in config["venues"]:
        # Ignore accidental blank entries in venues.yml.
        if not isinstance(source, dict):
            print(
                "WARN Skipping empty venue configuration entry",
                file=sys.stderr,
            )
            continue

        try:
            found = scrape_one(source)
            events.extend(found)

            status.append(
                {
                    "venue": source["name"],
                    "ok": True,
                    "events": len(found),
                    "url": source["url"],
                }
            )

            print(
                f"OK {source['name']}: {len(found)}"
            )

        except Exception as exc:
            status.append(
                {
                    "venue": source.get(
                        "name",
                        "Unknown venue",
                    ),
                    "ok": False,
                    "events": 0,
                    "url": source.get("url", ""),
                    "error": str(exc)[:180],
                }
            )

            print(
                (
                    f"WARN "
                    f"{source.get('name', 'Unknown venue')}: "
                    f"{exc}"
                ),
                file=sys.stderr,
            )

    now = datetime.now(TZ)

    unique_events = {
        item["id"]: item
        for item in events
        if valid_future(item, now)
    }

    payload = {
        "generatedAt": datetime.now(TZ).isoformat(),
        "events": sorted(
            unique_events.values(),
            key=lambda item: item["start"],
        ),
        "sources": status,
    }

    docs_directory = ROOT / "docs"
    docs_directory.mkdir(exist_ok=True)

    (docs_directory / "events.json").write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    if not unique_events:
        raise SystemExit(
            "No events were extracted; "
            "refusing to publish an empty calendar"
        )


if __name__ == "__main__":
    main()

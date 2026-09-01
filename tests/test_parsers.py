from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from scrape import TZ, parse_festival_hall_soup, parse_local, parse_night_market_soup, parse_offcut_soup, parse_submissions_csv, times_in, valid_future

def test_times_support_punctuation_and_ranges():
    assert times_in("4:30 pm No cover") == ["4:30 pm"]
    assert times_in("10:30 am to 4:30 pm") == ["10:30 am", "4:30 pm"]
    assert times_in("Doors 6:30 pm. Show: 7:30 pm.") == ["7:30 pm."]

def test_calgary_timezone_is_attached():
    parsed=parse_local("September 4, 2026","8:30 pm")
    assert parsed.hour == 20 and parsed.minute == 30 and parsed.tzinfo is not None

def test_past_and_malformed_events_are_removed():
    now=datetime.now(TZ)
    base={"title":"Test","venue":"Test","url":"https://example.com","id":"1"}
    assert not valid_future({**base,"start":(now-timedelta(minutes=1)).isoformat()},now)
    assert valid_future({**base,"start":(now+timedelta(minutes=1)).isoformat()},now)
    assert not valid_future({**base,"start":"not a date"},now)

def test_festival_hall_filter_is_exact():
    html='''<div class="event-full-item"><div class="event-feature-info"><span>07 Sep</span><span>7 PM</span><span>Festival Hall</span></div><div class="event-info"><p class="headline-6">Keep Me</p></div><a class="event-link" href="https://example.com/keep"></a></div>
    <div class="event-full-item"><div class="event-feature-info"><span>21 Oct</span><span>7 PM</span><span>The Bella Concert Hall</span></div><div class="event-info"><p class="headline-6">Exclude Bella</p></div></div>
    <div class="event-full-item"><div class="event-feature-info"><span>13 Sep</span><span>7 PM</span><span>The Palace Theatre</span></div><div class="event-info"><p class="headline-6">Exclude Palace</p></div></div>'''
    got=parse_festival_hall_soup(BeautifulSoup(html,"html.parser"),{"name":"Festival Hall","url":"https://example.com"})
    assert [x["title"] for x in got] == ["Keep Me"]

def test_offcut_requires_explicit_schedule_and_builds_thursdays():
    source={"name":"The Nash / Offcut Bar","url":"https://www.offcutbar.com/sesh"}
    got=parse_offcut_soup(BeautifulSoup("<main>Live Music Thursdays 7-9pm No Cover</main>","html.parser"),source)
    assert got and all(datetime.fromisoformat(x["start"]).weekday()==3 for x in got)
    assert all(datetime.fromisoformat(x["end"]).hour==21 for x in got)
    assert parse_offcut_soup(BeautifulSoup("<main>No schedule posted</main>","html.parser"),source)==[]

def test_night_market_extracts_every_date_and_inherits_month():
    source={"name":"Inglewood Night Market","url":"https://www.inglewoodnightmarket.ca/"}
    html="<main>May 8, June 12, July 10, August 14, September 4 and 11 2026, from 5pm to 10pm!</main>"
    got=parse_night_market_soup(BeautifulSoup(html,"html.parser"),source)
    assert len(got)==6
    assert [x["start"][5:10] for x in got]==["05-08","06-12","07-10","08-14","09-04","09-11"]
    assert all(x["start"][11:16]=="17:00" and x["end"][11:16]=="22:00" for x in got)

def test_google_sheet_submissions_are_validated_and_optionally_approved():
    csv_text='''Event name,Venue,Start date,Start time,End date,End time,Event URL,Description,Approved
Good Show,Test Hall,September 20 2026,7:30 pm,September 20 2026,9:00 pm,https://example.com/good,Live music,Yes
Rejected Show,Test Hall,September 21 2026,7:30 pm,,,https://example.com/nope,,No
Bad Link,Test Hall,September 22 2026,7:30 pm,,,javascript:alert(1),,Yes
'''
    got=parse_submissions_csv(csv_text,"https://forms.google.com/example")
    assert [x["title"] for x in got]==["Good Show","Bad Link"]
    assert got[0]["end"].endswith("21:00:00-06:00")
    assert got[1]["url"]=="https://forms.google.com/example"

from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from scrape import TZ, parse_festival_hall_soup, parse_local, times_in, valid_future

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

# HubSpot live run, 19 Oct 2026

Until 0.3.0 the HubSpot adapter had only been tested against a mock of the API. These runs put it against a real portal: a HubSpot developer test account (EU data centre), a service key with contact and deal scopes, and `scripts/hubspot_live_check.py`.

The script takes every enquiry from two people per kind of repeat in `seed/enquiries.jsonl`, plus eight one-off enquirers: 29 enquiries from 16 people. It tags each email and shifts each phone so every run starts clean, then posts the enquiries back to back, with no pause between them. That is harsher than real traffic on purpose: a double click lands about a second after the first click. Replies are drafted by the template drafter, so no model is called.

## What the mock did not show

The first live run stopped at enquiry 8, a double click:

```
HubSpot POST /crm/v3/objects/contacts -> 409:
{"status":"error","message":"Contact already exists. Existing ID: 895935814889","category":"CONFLICT"}
```

HubSpot's search index trails its writes by a few seconds. The contact created by the first click was not searchable yet, so the engine tried to create it again, and HubSpot refused because emails are unique. A mock answers from memory, instantly, so it never showed this. The same lag hits deal search: a deal created a second ago is not found, and a second deal would be opened.

## The fix (0.3.0)

1. **A 409 that names the existing contact is a match, not an error.** The adapter reads the id from HubSpot's message and patches that contact.
2. **The open deal is read through the associations API**, which reads the record itself rather than the search index, so a deal created a second ago is already there.
3. **The engine trusts its own recent writes.** For `CRM_SEARCH_LAG_SECONDS` (default 120) after it wrote a contact, a repeat with the same email or phone reuses it even if the CRM's search misses it. This also covers the case the 409 cannot: the same phone with a different email, because phones are not unique in HubSpot.

## Results after the fix

Two runs: one as shipped, one with the engine's own record turned off (`CRM_SEARCH_LAG_SECONDS=0`) to check that the 409 path works on its own.

| Measure | Default (120 s) | Engine record off (0) |
|---|---|---|
| Enquiries / people | 29 / 16 | 29 / 16 |
| Repeats in the sample | 13 | 13 |
| Contacts in HubSpot / expected | 16 / 16 | 16 / 16 |
| **People with more than one contact** | **0** | **0** |
| First enquiries merged into someone else's contact | 0 | 0 |
| Contacts with more than one deal | 0 | 0 |
| Contacts without a deal | 0 | 0 |
| Repeats found by HubSpot search | 7 | 9 |
| Repeats the search missed, caught by the engine's own record | 6 | 0 |
| Repeats the search missed, caught by the 409 | 0 | 4 |
| Time per enquiry, engine and HubSpot API | 1.00 s | 1.09 s |

Repeats in the sample: 2 double clicks, 3 with the same email in a different case, 4 with the same phone in a different format, 2 later enquiries, 2 with a new phone. Runs `r1019b120` and `r1019b0`, 19 Oct 2026 19:15 and 19:16 UTC.

Between a third and a half of the repeats arrived before HubSpot's search had caught up. Every one of them still landed on the right contact and the right deal.

## A note on the check itself

The seed's phones sit in Ofcom's drama range, 07700 900000 to 900999, so there are only a thousand of them. An earlier version of the script shifted phones by a fixed amount, and four "new" people landed on numbers that contacts from a previous run already had. The engine matched them by phone, exactly as it should, and the check counted that as correct. The script now picks a shift that collides with no phone already in the portal, and it reports two extra numbers: first enquiries merged into an existing contact, and matched contacts created before the run. Both must be zero for the run to pass.

## Run it on your own portal

Use a developer test account, not a live portal: the script creates real contacts and deals.

```bash
HUBSPOT_ACCESS_TOKEN=... python scripts/hubspot_live_check.py --markdown docs/hubspot-live-run.md
```

It exits 0 only when every person has exactly one contact with exactly one deal, nothing was merged into an older contact, and the contact count matches the people in the sample.

---
description: Start a lead-generation campaign - brief, ICP, source plan - and stop for your yes before collecting
argument-hint: <what you sell> [to whom] [where]
---

Start a new lead-generation campaign for: $ARGUMENTS

Use the `lead-gen` skill for the overall flow, and do only its steps 0–2 now:

1. **Campaign**: pick a short slug from the offer and market (e.g. `dental-booking-porto`). Check it's free with
   `leadgen status <slug> --json` (an error means it's free), then `leadgen init <slug> --offer "<one line>"`.
2. **Brief and ICP**: follow the `icp-builder` skill. Ask the missing questions in one message. If the user
   named a website, read it first and propose answers. Write `brief.md` and the `[campaign]`, `[[scoring.rules]]`
   and `[outreach]` stubs in `campaign.toml`. Leave `send_mode = "off"`.
3. **Source plan**: follow the `lead-sourcing` skill. Write small `[[sources]]` blocks (one location, low
   limits) and check readiness with `leadgen sources`.

Then show the ICP table (criterion → observable field → rule) and the source plan, and **stop**. Collect only
after the user says yes. Then `/leadgen:run <slug>` does the rest.

If the arguments are empty, ask what they sell, to whom, and where, in one message.

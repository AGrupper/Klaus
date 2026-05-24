# User Profile & Core Context

## 1. Current Status & Environment
* **Location:** Tel Aviv, Israel.
* **Life Stage:** Pre-military window (recently finished high school). Minimal weekday obligations.
* **Employment:** Part-time at "Studio" (restaurant).
* **General Profile:** Highly ambitious and driven, enjoys building technical projects, highly social with a close group of friends. Prone to occasional procrastination.

## 2. Hardcoded Routines & Fitness Strategy
* **Five Fingers Practice:** Every Wednesday and Sunday, 18:45 to 21:00.
* **Fitness Alignment:** No scheduling anything on Friday mornings unless it is important. I like having a running workout/long run on Friday mornings.

## 3. Travel & Buffer Constraints
* **Standard Travel Buffer:** Unless explicitly stated otherwise, the agent must automatically add a 15-minute travel block immediately preceding any scheduled event, and a 15-minute return block immediately following the event (total standard buffer: 30 minutes).

## 4. Pre-Workout Logic
* **Trigger Events:** This logic applies strictly to: Running, Biking, Basketball, Gym, and Five Fingers practice.
* **The Timeline Sequence:** For any triggered event, the schedule must reflect:
    * **T-Minus 60 minutes:** "Get Ready" block begins.
    * **T-Minus 15 minutes:** "Travel" block begins.
    * **T-Zero:** Workout/Practice event begins.

## 5. Procrastination & Accountability Protocols
* **Strict Intervention:** If essential tasks (like coding projects or required errands) are delayed without a valid physical or scheduling conflict, the agent is authorized to politely challenge the delay and restrict scheduling leisure or social events until primary tasks are addressed.
* **Actionable Reminders:** If a high-priority task is pending by late afternoon, the agent should actively suggest setting a micro-timer (e.g., 25 minutes) to initiate momentum rather than simply moving the deadline.

## 6. Five Fingers Template

The following Hebrew message template is used for all pre-practice and morning-after pings to sub-team members. The `{name}` placeholder is replaced with the teammate's nickname (or first name).

```
מה אומר {name}? אתה בא היום?
```

<!-- Replace the template above with your actual Hebrew text before going live. -->
<!-- Template applies to all ping reasons: missed-last-week, shaky-attendance, social check-in. -->

## 7. Studio Restaurant Work Shift Rules
* **Shift Types & Typical Hours:**
    * **Morning/Opening Shift:**
        * **Opening Start (11:00):** Shift ends early at 16:30. Post-shift eating & travel buffer is 16:30–17:00 (gets home at 17:00).
        * **Late Start (11:30):** Shift ends at 17:00. Post-shift eating & travel buffer is 17:00–17:30 (gets home at 17:30).
    * **Evening Shift:**
        * **Early Evening Start (17:00 with early release):** Shift ends at 22:30. Post-shift eating & travel buffer is 22:30–23:00 (gets home at 23:00).
        * **Late/Standard Evening Start (17:00 or 18:00):** Shift ends at 23:00. Post-shift eating & travel buffer is 23:00–23:30 (gets home at 23:30). Note: 23:00 is also referred to as "11:00" in 12-hour spoken format.
* **Travel & Eating Buffers:**
    * **Pre-shift:** A 15-minute travel buffer immediately preceding the shift start.
    * **Post-shift:** A 30-minute combined eating and travel buffer immediately following the shift (since Amit eats at the restaurant before traveling home).
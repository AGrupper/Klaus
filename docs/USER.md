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
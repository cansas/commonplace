# Night Owl achievement: consider local time

The Night Owl achievement currently checks UTC hour (`0 <= hour < 5`).
Consider changing it to use the user's local timezone instead, so it
triggers based on their actual local late-night hours, not a fixed UTC
window.

**Code location:** `app/services/achievements.py:159-161`

**Current check:**

```python
elif ach["check"] == "night_owl":
    unlocked = review_hour is not None and 0 <= review_hour < 5
```

The `review_hour` is passed in from the review submission handler, which
uses `datetime.utcnow().hour`. To use local time, the server would need
to know the user's timezone (currently it doesn't track that — feature
work needed).

**Possible approaches:**

1. Add a timezone preference to user settings
2. Use HTTP `Accept-Timezone` header / JS to send client UTC offset with
   the review
3. Make the check configurable (night owl window slider in settings)

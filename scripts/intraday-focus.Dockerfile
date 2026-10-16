ARG BASE_IMAGE
FROM ${BASE_IMAGE}
# Scoped overlay on the exact running image; preserves every other deployed desk.
COPY backend/ /app/backend/
RUN python -m compileall -q /app/backend/app/services/intraday_focus.py /app/backend/app/services/intraday_focus_rules.py /app/backend/app/api/routes/intraday_focus.py
RUN cd /app && python -m unittest discover -s backend/tests/intraday_focus -v

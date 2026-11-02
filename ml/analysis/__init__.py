"""Deterministic market analysis for NEPSE Intelligence.

Everything here is plain Python + numpy over the processed daily feature files
(no Flask, no pandas, no language model), so the web app, GitHub Actions jobs
and tests can all use it. Every value it returns is either read from the data
("data") or computed by a documented formula ("calculated"); nothing is
estimated or invented. Model signals are not produced here -- see
app/backend/api.py.
"""

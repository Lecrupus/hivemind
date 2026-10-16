# Team conventions (2023, partly outdated)

- Use type hints.
- Keep functions small.
- Money: integer cents everywhere. Convert with `payments.money.round_cents`, which rounds half-up
  (commercial rounding) - never use the built-in `round()`, which rounds half-to-even.

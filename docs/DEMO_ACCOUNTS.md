# Demo accounts

Logins for walking through both sides of DineMate. Recreate or reset them at any
time — the command is idempotent and always resets the password to the one below,
so this file cannot drift from reality:

```bash
cd backend && uv run python -m app.cli seed-demo
```

**Password for every account: `DineMate2026!Demo`**

## Customers — sign in at http://localhost:3000

| Name | Email |
| --- | --- |
| Ayesha Khan | `ayesha.khan@dinemate.app` |
| Bilal Ahmed | `bilal.ahmed@dinemate.app` |

Chat, browse the menu, build a basket across kitchens, and track orders at
`/orders`.

## Kitchen staff — sign in at http://localhost:3000/kitchen

| Name | Email | Kitchen |
| --- | --- | --- |
| Imran Malik | `imran.lahori@dinemate.app` | Lahori Charga House |
| Sana Qureshi | `sana.karachi@dinemate.app` | Karachi Seekh & Broast |
| Adnan Shah | `adnan.sindhi@dinemate.app` | Sindhi Biryani Co |
| Gulzar Khan | `gulzar.peshawari@dinemate.app` | Peshawari Namak Mandi |
| Nadia Iqbal | `nadia.chaikhana@dinemate.app` | Chai Khana |

Each chef sees **only their own kitchen's tickets**. No route accepts a
restaurant id — the kitchen comes from the signed-in account — and a customer
hitting any `/api/kitchen/*` route gets `404`, not `403`, because a 403 would
confirm the route exists.

## These are demonstration accounts

They exist to make the app openable, and the password is in version control.
Never run `seed-demo` against production, and never promote a real person's
account this way — use `python -m app.cli staff <email> <restaurant-id> <password>`
for a genuine staff account with a password nobody else has seen.

## If sign-in does not work

- **The password box is pre-filled and the wrong password is submitted.** Chrome
  autofills a saved credential for `localhost`. Clear the field before typing.
- **Everything returns 401 straight after signing in.** The page origin and
  `NEXT_PUBLIC_API_URL` must share a host: a cookie set for `localhost` is never
  sent to `127.0.0.1`. Both are `localhost` by default — keep them that way.
- **The kitchen page shows "your account is not attached to a restaurant".** The
  account is a customer. Sign in as one of the chefs above.

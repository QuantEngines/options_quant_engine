from breeze_connect import BreezeConnect
import json

# -------------------------------
# INSERT YOUR CREDENTIALS HERE
# -------------------------------
API_KEY = "48nWvK1@5m595035578JvN488P7X2336"
SECRET_KEY = "Y8eP1*B8370902vAmE59262g5u372r2$0"
SESSION_TOKEN = "54993310"
# -------------------------------

breeze = BreezeConnect(api_key=API_KEY)

breeze.generate_session(
    api_secret=SECRET_KEY,
    session_token=SESSION_TOKEN
)

print("\nSession initialized\n")

try:

    resp = breeze.get_option_chain_quotes(
        stock_code="NIFTY",
        exchange_code="NFO",
        product_type="options",
        right="call",
        strike_price="23350",
        expiry_date="2026-03-19T06:00:00.000Z"
    )

    print("Response:\n")
    print(json.dumps(resp, indent=2)[:2000])

except Exception as e:

    print("ERROR:", e)
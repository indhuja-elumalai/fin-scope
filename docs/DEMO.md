# 75-second demo script

Setup: seeded data (`make seed-demo`, or `--reasoning` to include a stored
Claude result), browser at 1440×900. Open the site once beforehand so the API
is awake (the top bar should read **API ONLINE**).

| Time | Do this | Say this |
| --- | --- | --- |
| 0:00 | **Command center** (`/`). Point at the status dial and stat tiles. | "FIN-SCOPE watches a merchant's payment events and runs an incident loop: find, explain, simulate, decide, act, verify. Three merchants, two incidents, all systems nominal." |
| 0:08 | Point at the **Control loop** panel on the right. | "One step uses AI, highlighted in violet. Everything else is deterministic code with an audit trail." |
| 0:13 | In **Recent investigations**, click **Aurora Retail (demo)**. | "Six failed or delayed payments in 60 minutes crossed the FIND threshold." |
| 0:18 | Point at the **control-loop stepper**, then **Dominant signal** and **Financial impact** (both tagged FACT). | "Here are the stages, the dominant signal, and the impact in rupees. Facts are labelled as facts." |
| 0:25 | Scroll to **Reasoning** (tagged INFERENCE). | "Claude proposes ranked root-cause hypotheses. Each must cite real evidence IDs or the response is rejected, and it's labelled as inference, never fact." *(If not seeded with reasoning: "On the public demo this call is switched off to control cost.")* |
| 0:37 | Scroll to **Consequence simulation**. | "Each scenario is projected deterministically, with its assumptions shown." |
| 0:44 | Scroll to **Decision evaluation**; point at **Recommendation** and **Authorization: POLICY · ALLOWED**. | "Code picks the best scenario, and a separate, versioned policy engine decides whether we may act: exposure under ₹5,000, under 25 events, no unknown amounts." |
| 0:53 | Scroll to **Sandbox action**; point at the executed result. | "The action only runs when policy allows it and a person clicks. It's a sandbox, or Razorpay's TEST API, never live money." |
| 1:00 | Scroll to **Outcome verification**. | "Then we check reality against the projection. When they don't match, it says *Failed* or *Partially verified* instead of claiming success." |
| 1:07 | Back to **Investigations**, open **Northwind Travel (demo)**, scroll to **Decision evaluation**. | "Bigger amounts: policy says *requires human approval*, so there's no action button at all." |
| 1:13 | — | "Next.js and FastAPI on Postgres, with 352 backend tests in CI. Thanks!" |

Tips: hide the bookmarks bar, zoom to 100%, and record at 30 fps. Cut any pause
while the free-tier API wakes up.

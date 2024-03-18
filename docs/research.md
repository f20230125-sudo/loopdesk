# Public context and design rationale

Sources below were supplied in the prior research plan, which reported checking them on **24 October 2026**. Company and person claims were not independently re-audited during implementation. The software deployment guide was opened during implementation. This note separates public company context from assumptions in the prototype. The recruitment email and application details remain in excluded private notes.

## Company context

- [Madenat official website](https://madenatrecycling.ae/): recycling services including electronic waste, batteries, data destruction and IT asset disposition. This informed the three sample service categories; it is not an exhaustive company catalogue.
- [Official lithium-ion battery services page](https://madenatrecycling.ae/lithium-ion-battery-recycling-in-dubai-uae): battery-related commercial context, including electronics, EVs, power tools and renewable energy. No safety or process guidance is copied into LoopDesk.
- [Recycling Expo Middle East profile](https://www.recyclingexpome.com/exhibitors/madenat-alnokhba-recycling-services-llc): lists Joseph Nforbin as Founder & CEO. This is a public professional association, not verification of a software hiring manager.
- [Sara Nasser public professional profile](https://ae.linkedin.com/in/sara-tawfiq-nasser-bat) and [Bih Linda Gamon public professional profile](https://ae.linkedin.com/in/bih-linda-gamon-2b9b511b6): examples of publicly associated business-development work. Their involvement in hiring or this prototype is unverified. Their names and contact details are not used as demo users.
- [LinkedIn company profile](https://www.linkedin.com/company/madenat-al-nokhba-recycling-services-llc): prior research reported a 2015 founding date. Do not equate an expertise claim with company age.
- [February 2024 industry interview](https://www.wasterecyclingmea.com/top-stories/madenat-al-nokhba-all-set-to-revolutionise-lithium-ion-battery-recycling-in-the-gcc): contains a different title and capacity figure from the expo profile. The scopes are not established as comparable. No capacity, certification or regional-first claim is used in the application.

## Project assumptions

The internship's requested capabilities are contact management, pipeline tracking and reporting dashboards. LoopDesk demonstrates those directly. Six pipeline stages, free-text owners, three service categories, AED estimates, 24-hour demos and fictional follow-up examples are portfolio design decisions. They are not confirmed company requirements or an account of Madenat's current workflow.

No technology preference, AI requirement or named software department was verified. No separate public vacancy or hiring manager was verified. The university notice governs role alignment; public profiles do not override it.

## Unresolved questions

- What fields, upload restrictions and sign-in requirements appear in the application form? The browsing tool could not access it.
- Is the deadline explicitly Dubai time? The plan used Dubai time because the university and placement are in Dubai; the notice did not specify a timezone.
- What are the team's actual pipeline stages, owners, approval rules and reporting periods? These require stakeholder discovery if the placement proceeds.
- What authentication, data retention, company integrations and operating controls would be required for real customer information? They are outside this fictional demonstration.

## Implementation reference

[Vercel's Flask deployment documentation](https://vercel.com/docs/frameworks/backend/flask) describes recognised Flask entrypoints and `public/` CDN assets. The prepared package follows that layout, but no live deployment is claimed.

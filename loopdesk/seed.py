"""Deterministic fictional content; UUID identifiers differ per workspace."""
from datetime import datetime, timedelta

from .services import OWNERS, SERVICES, STAGES, audit, dubai_today, insert, uid

NAMES = [
    "Cedar Circuit", "Dune Orbit", "Harbour Fern", "Copper Finch", "Amber Relay",
    "Palm Mosaic", "Silver Canopy", "Coral Lattice", "Saffron Switch", "Willow Beacon",
    "Juniper Stack", "Indigo Parcel", "Linen Current", "Quartz Meadow", "Olive Junction",
    "Pearl Compass", "Maple Signal", "Ivory Circuit", "Terra Loom", "Beryl Works",
    "Acacia Relay", "Cobalt Garden", "Ochre Node", "Sable Horizon", "Citrine Bay",
    "Birch Summit", "Sienna Link", "Jade Workshop", "Opal Network", "Teal Lantern",
]


def seed_workspace(db, wid):
    now = datetime.fromisoformat(db.one("SELECT created_at FROM workspaces WHERE id=?", (wid,))["created_at"])
    orgs, contacts = [], []
    for i, name in enumerate(NAMES):
        oid, cid = uid(), uid()
        orgs.append(oid)
        contacts.append(cid)
        insert(db, "organisations", dict(id=oid, workspace_id=wid, name=name,
               sector=("Electronics retail", "Renewable energy", "Business services", "Logistics", "Hospitality")[i % 5],
               city=("Dubai", "Abu Dhabi", "Sharjah")[i % 3]))
        insert(db, "contacts", dict(id=cid, workspace_id=wid, organisation_id=oid,
               name=("Alex", "Jordan", "Sam", "Taylor", "Riley")[i % 5] + f" Example {i+1:02}",
               email=f"contact{i+1:02}@organisation{i+1:02}.example.com", role="Operations coordinator"))
    for i in range(36):
        idx = i % 30
        rid, stage = uid(), STAGES[i % 6]
        created = (now - timedelta(days=45 - i % 12)).isoformat()
        entered = max(created, (now - timedelta(days=(i * 7) % 42)).isoformat())
        active = (now - timedelta(days=(i * 5) % 38)).isoformat()
        service_index = (i // 6 + i // 2) % 3
        service = SERVICES[service_index]
        title = ("Quarterly battery collection", "Office electronics refresh", "Retired IT equipment review")[service_index]
        next_action = {"New": "Confirm material type and collection location", "Contacted": "Arrange an introductory call", "Qualified": "Confirm scope and collection schedule", "Proposal": "Follow up on the proposed service scope", "Won": "Hand over the agreed scope to operations", "Lost": "Record feedback and revisit next quarter"}[stage]
        insert(db, "opportunities", dict(id=rid, workspace_id=wid, organisation_id=orgs[idx], contact_id=contacts[idx],
               title=f"{title} · {idx+1:02}", service=service, owner=OWNERS[(i + i // 6) % 3], stage=stage,
               value_minor=None if i % 5 == 0 else (i+4)*125000, next_action=next_action, created_at=created))
        db.execute("INSERT INTO stage_events(id,workspace_id,opportunity_id,from_stage,to_stage,created_at) VALUES (?,?,?,?,?,?)",
                   (uid(), wid, rid, None, "New", created))
        if stage != "New":
            db.execute("INSERT INTO stage_events(id,workspace_id,opportunity_id,from_stage,to_stage,created_at) VALUES (?,?,?,?,?,?)",
                       (uid(), wid, rid, "New", stage, entered))
        audit(db, wid, "opportunity", rid, "Fictional enquiry prepared for this demo.", rid, "created")
        db.execute("UPDATE activities SET created_at=? WHERE workspace_id=? AND opportunity_id=? AND kind='created'", (created, wid, rid))
        audit(db, wid, "opportunity", rid, "Fictional collection scope discussed with the contact.", rid, "note")
        db.execute("UPDATE activities SET created_at=? WHERE workspace_id=? AND opportunity_id=? AND kind='note'", (max(created, entered, active), wid, rid))
        if stage not in ("Won", "Lost"):
            insert(db, "tasks", dict(id=uid(), workspace_id=wid, opportunity_id=rid,
                   title=next_action, due_date=(dubai_today(now) + timedelta(days=(i // 6) - 2)).isoformat(), completed=0))

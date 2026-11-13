#!/usr/bin/env python3
"""Idempotent BigQuery (`cymbal_retail_my`) and Knowledge Studio provisioner.

Provisions:
1. BigQuery dataset `<GCP_PROJECT_ID>.cymbal_retail_my` (location `US`) with two tables
   whose physical column descriptions are intentionally left NULL ("Dumb Data"):
   - `users` (contains deprecated `legacy_vip_flag` alongside `traffic_source` and `age`)
   - `orders_raw_v2` (contains `ord_stat_cd`: 1=Completed, 2=Returned, 9=Cancelled, 99=QA Sandbox)

2. Google Cloud Knowledge Studio / Knowledge Catalog (Dataplex) governed semantic layer:
   - Knowledge Studio Context Set (`cymbal_retail_my_context_set`, `type="context-set"`)
     with 3 certified policy entries (`customer_segmentation_policy`,
     `governed_net_revenue_metric`, `order_status_and_qa_exclusion`) and 4 `reference`
     EntryLinks pointing to `@bigquery` tables `users` and `orders_raw_v2`.
   - Policy EntryGroup (`cymbal_retail_my_policies`) with consolidated policy entry.
   - `dataplex-types.global.overview` aspects attached to `@bigquery` table entries.
   - Business Glossary (`cymbal_retail_my_glossary`) with governed terms.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request

import google.auth
import google.auth.transport.requests
from google.api_core import exceptions as gcp_exceptions
from google.cloud import bigquery, dataplex_v1
from google.protobuf import field_mask_pb2, struct_pb2

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed_demo")

DATASET_ID = "cymbal_retail_my"
BQ_LOCATION = "US"
KC_ENTRY_LOCATION = "us"
KC_GLOSSARY_LOCATION = "global"
CONTEXT_SET_ID = "cymbal_retail_my_context_set"
POLICY_ENTRY_GROUP_ID = "cymbal_retail_my_policies"
POLICY_ENTRY_ID = "customer_segmentation_and_revenue_policy"
GLOSSARY_ID = "cymbal_retail_my_glossary"


def resolve_project_id() -> str:
    """Resolve the target GCP Project ID from environment or active gcloud config."""
    env_proj = (os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if env_proj and not env_proj.startswith("<"):
        return env_proj
    try:
        out = subprocess.check_output(
            ["gcloud", "config", "get-value", "project"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out and out != "(unset)":
            return out
    except (OSError, subprocess.CalledProcessError):
        pass
    raise SystemExit("Error: Set GCP_PROJECT_ID in .env or export GCP_PROJECT_ID=<your-project-id> before seeding.")


def resolve_project_number(project_id: str, token: str) -> str:
    """Look up the numeric GCP Project Number via Cloud Resource Manager REST or gcloud."""
    env_num = (os.environ.get("GCP_PROJECT_NUMBER") or "").strip()
    if env_num.isdigit():
        return env_num
    try:
        req = urllib.request.Request(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}",
            headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project_id},
        )
        data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        if data.get("projectNumber"):
            return str(data["projectNumber"])
    except (OSError, ValueError):
        pass
    out = subprocess.check_output(
        ["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"],
        text=True,
    ).strip()
    if not out.isdigit():
        raise RuntimeError(f"Could not resolve numeric projectNumber for {project_id!r}.")
    return out


def get_oauth_token() -> str:
    """Obtain an OAuth 2.0 Bearer token from Google Cloud Application Default Credentials."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not creds.valid or not creds.token:
        creds.refresh(google.auth.transport.requests.Request())
    if not creds.token:
        raise RuntimeError("Failed to obtain Google Cloud ADC token. Run: gcloud auth application-default login")
    return str(creds.token)


def build_policy_markdown(project_id: str) -> str:
    return f"""# Cymbal Retail Malaysia — Governed Customer Segmentation & Net Revenue Policy (FY2026)

- **Owner**: CRM & Finance Governance Council (Kuala Lumpur)
- **Applies To**: `{project_id}.{DATASET_ID}.users`, `{project_id}.{DATASET_ID}.orders_raw_v2`
- **Status**: CERTIFIED AUTHORITATIVE

## 1. Canonical Definition: `Premium Customer`
A **Premium Customer** in Cymbal Retail Malaysia is defined strictly by **all three** criteria:
1. **Acquisition Channel**: `users.traffic_source = 'Email'`
2. **Customer Age**: `users.age >= 35`
3. **Verified Purchase History**: At least 1 completed order (`orders_raw_v2.ord_stat_cd = 1`)

> **CRITICAL DEPRECATION WARNING (`users.legacy_vip_flag`)**:
> **NEVER** filter or group by `users.legacy_vip_flag`! That boolean column is an abandoned 2023 promotional import that was frozen and includes non-email signups, underage accounts, and internal QA test accounts.

## 2. Canonical Definition: `Governed Net Revenue (MYR)`
**Net Revenue** (and any headline "Revenue" metric reported for Cymbal Retail Malaysia) MUST be computed as:

```sql
SUM(o.amt_gross_myr - o.disc_myr)
WHERE o.ord_stat_cd = 1
```

### Mandatory `ord_stat_cd` Status Code Reference
| `ord_stat_cd` | Meaning | Include in Revenue? |
| :--- | :--- | :--- |
| `1` | **Completed & Settled Customer Order** | **YES** (Authoritative) |
| `2` | **Customer Returned / Refunded Order** | **NO** — Exclude |
| `9` | **Payment Cancelled / Voided Order** | **NO** — Exclude |
| `99` | **Internal Engineering Load-Test / QA Sandbox Row** | **NO** — Strictly Exclude |
"""


ORDERS_OVERVIEW_MD = f"""# `{DATASET_ID}.orders_raw_v2` — Governed Table Contract

Order ledger for Cymbal Retail Malaysia (`MYR`).

- **Primary Key**: `order_id` (`STRING`), joins to `{DATASET_ID}.users.user_id` on `user_id`.
- **Governed Net Revenue Formula**: `SUM(amt_gross_myr - disc_myr)` filtered strictly to `ord_stat_cd = 1`.
- **Status Codes (`ord_stat_cd`)**:
  - `1` = Completed & settled order (**ONLY valid revenue status**)
  - `2` = Returned / refunded order (exclude)
  - `9` = Cancelled / payment voided (exclude)
  - `99` = Internal load-test / QA sandbox synthetic rows (**MUST EXCLUDE** — never include in analytics)
"""

USERS_OVERVIEW_MD = f"""# `{DATASET_ID}.users` — Governed Customer Dimension Contract

Registered customer accounts across Malaysia (`Kuala Lumpur`, `Selangor`, `Penang`, `Johor`).

- **Primary Key**: `user_id` (`STRING`).
- **DEPRECATED TRAP COLUMN**: `legacy_vip_flag` (`BOOL`) is **DEPRECATED (2023 campaign leftover — DO NOT USE)**.
- **Canonical `Premium Customer` Rule**:
  1. `traffic_source = 'Email'`
  2. `age >= 35`
  3. Has at least one order in `{DATASET_ID}.orders_raw_v2` with `ord_stat_cd = 1`.
"""


def _run_bq_ddl(client: bigquery.Client, sql: str) -> None:
    job_config = bigquery.QueryJobConfig(
        use_legacy_sql=False,
        labels={"app": "knowledgestudio-devfest2026"},
    )
    client.query(sql, job_config=job_config).result(timeout=90.0)


def seed_bigquery_tables(bq: bigquery.Client, project_id: str) -> None:
    """Create `cymbal_retail_my` and populate deterministic `users` and `orders_raw_v2` tables."""
    ds_ref = bigquery.Dataset(f"{project_id}.{DATASET_ID}")
    ds_ref.location = BQ_LOCATION
    bq.create_dataset(ds_ref, exists_ok=True)
    log.info("Ensured BigQuery dataset %s.%s (%s)", project_id, DATASET_ID, BQ_LOCATION)

    _run_bq_ddl(
        bq,
        f"""
        CREATE OR REPLACE TABLE `{project_id}.{DATASET_ID}.users` AS
        SELECT * FROM UNNEST([
          -- True governed Premium Customers (traffic_source='Email' AND age >= 35): U001..U004
          STRUCT('U001' AS user_id, 'Aisyah Rahman' AS full_name, 'Kuala Lumpur' AS state, 38 AS age, 'Email' AS traffic_source, TRUE AS legacy_vip_flag, DATE '2024-02-10' AS signup_date),
          STRUCT('U002', 'Tan Wei Ming', 'Penang', 42, 'Email', TRUE, DATE '2024-03-18'),
          STRUCT('U003', 'Priya Nair', 'Selangor', 36, 'Email', FALSE, DATE '2024-06-05'),
          STRUCT('U004', 'Farid Iskandar', 'Johor', 45, 'Email', TRUE, DATE '2024-08-22'),
          -- Trap users: legacy_vip_flag=TRUE, but NOT governed Premium (Age < 35 / TikTok_Ads / Paid_Search / QA)
          STRUCT('U005', 'Daniel Lim', 'Kuala Lumpur', 27, 'Email', TRUE, DATE '2023-11-01'),
          STRUCT('U006', 'Nurul Huda', 'Selangor', 41, 'TikTok_Ads', TRUE, DATE '2023-09-14'),
          STRUCT('U007', 'Chong Kar Wai', 'Penang', 39, 'Paid_Search', TRUE, DATE '2023-10-30'),
          STRUCT('U008', 'Cymbal QA LoadTest Bot', 'Kuala Lumpur', 50, 'Internal_QA', TRUE, DATE '2023-01-01'),
          -- Standard non-VIP customers
          STRUCT('U009', 'Hafiz Zulkifli', 'Johor', 29, 'Organic', FALSE, DATE '2025-01-12'),
          STRUCT('U010', 'Mei Ling Wong', 'Sabah', 33, 'Referral', FALSE, DATE '2025-04-19')
        ])
        """,
    )

    _run_bq_ddl(
        bq,
        f"""
        CREATE OR REPLACE TABLE `{project_id}.{DATASET_ID}.orders_raw_v2` AS
        SELECT * FROM UNNEST([
          -- Governed Premium Customer Completed Orders (ord_stat_cd = 1) -> Net = RM 1,280,000.00
          STRUCT('ORD-2026-301' AS order_id, 'U001' AS user_id, TIMESTAMP '2026-07-14 10:15:00+08' AS order_ts, 360000.00 AS amt_gross_myr, 20000.00 AS disc_myr, 1 AS ord_stat_cd, 'Web' AS channel),
          STRUCT('ORD-2026-302', 'U002', TIMESTAMP '2026-08-03 14:30:00+08', 350000.00, 15000.00, 1, 'Mobile_App'),
          STRUCT('ORD-2026-303', 'U003', TIMESTAMP '2026-08-21 09:45:00+08', 340000.00, 20000.00, 1, 'Web'),
          STRUCT('ORD-2026-304', 'U004', TIMESTAMP '2026-09-11 16:20:00+08', 300000.00, 15000.00, 1, 'Mobile_App'),

          -- Trap Rows on Premium Users: Returned (2) & Cancelled (9) orders in Q3
          STRUCT('ORD-2026-305', 'U001', TIMESTAMP '2026-07-28 11:00:00+08', 42500.00, 2500.00, 2, 'Web'),
          STRUCT('ORD-2026-306', 'U002', TIMESTAMP '2026-09-19 18:10:00+08', 50000.00, 0.00, 9, 'Mobile_App'),

          -- Trap Rows on Stale legacy_vip_flag=TRUE Non-Premium Users
          STRUCT('ORD-2026-307', 'U005', TIMESTAMP '2026-07-22 13:05:00+08', 290000.00, 10000.00, 1, 'Mobile_App'),
          STRUCT('ORD-2026-308', 'U006', TIMESTAMP '2026-08-15 20:40:00+08', 332500.00, 10000.00, 1, 'Social_Shop'),
          STRUCT('ORD-2026-310', 'U007', TIMESTAMP '2026-09-02 15:15:00+08', 295000.00, 15000.00, 1, 'Web'),

          -- Trap Row: Internal Engineering Load-Test / QA Sandbox (ord_stat_cd = 99)
          STRUCT('ORD-2026-999-QA', 'U008', TIMESTAMP '2026-09-25 02:00:00+08', 420000.00, 0.00, 99, 'LoadTest_Runner'),

          -- Standard Non-VIP Completed Order in Q3
          STRUCT('ORD-2026-309', 'U009', TIMESTAMP '2026-09-05 12:00:00+08', 80000.00, 5000.00, 1, 'Web'),

          -- Q2 Historical Completed Order
          STRUCT('ORD-2026-201', 'U001', TIMESTAMP '2026-05-18 10:00:00+08', 110000.00, 5000.00, 1, 'Web')
        ])
        """,
    )
    log.info("Seeded `users` and `orders_raw_v2` in %s.%s", project_id, DATASET_ID)


def _make_overview_aspect(markdown_text: str) -> dataplex_v1.Aspect:
    aspect_data = struct_pb2.Struct()
    aspect_data.update({"content": markdown_text, "contentType": "MARKDOWN"})
    return dataplex_v1.Aspect(
        aspect_type="projects/dataplex-types/locations/global/aspectTypes/overview",
        data=aspect_data,
    )


def _make_generic_aspect() -> dataplex_v1.Aspect:
    return dataplex_v1.Aspect(
        aspect_type="projects/dataplex-types/locations/global/aspectTypes/generic",
        data=struct_pb2.Struct(),
    )


def _dataplex_rest(method: str, url: str, token: str, project_id: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": project_id,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def seed_knowledge_studio_context_set(project_id: str, project_number: str, token: str) -> None:
    """Create Knowledge Studio Context Set (`type="context-set"`), 3 entries, and 4 EntryLinks."""
    base = f"https://dataplex.googleapis.com/v1/projects/{project_id}/locations/{KC_ENTRY_LOCATION}"
    cs_url = f"{base}/entryGroups/{CONTEXT_SET_ID}"
    try:
        _dataplex_rest("GET", cs_url, token, project_id)
        log.info("Knowledge Studio Context Set already exists: %s", CONTEXT_SET_ID)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        op = _dataplex_rest(
            "POST",
            f"{base}/entryGroups?entryGroupId={CONTEXT_SET_ID}",
            token,
            project_id,
            {
                "displayName": "Cymbal Retail Malaysia — Governed Context Set",
                "description": "Certified customer segmentation policy, KPI formulas, and status code contracts for Cymbal Retail Malaysia (cymbal_retail_my).",
                "type": "context-set",
                "labels": {"domain": "cymbal_retail_my"},
            },
        )
        for _ in range(15):
            if op.get("done"):
                break
            time.sleep(2)
            op = _dataplex_rest("GET", f"https://dataplex.googleapis.com/v1/{op['name']}", token, project_id)
        log.info("Created Knowledge Studio Context Set: %s", CONTEXT_SET_ID)

    catalog = dataplex_v1.CatalogServiceClient(transport="rest")
    cs_parent = f"projects/{project_id}/locations/{KC_ENTRY_LOCATION}/entryGroups/{CONTEXT_SET_ID}"

    cs_entries = [
        (
            "customer_segmentation_policy",
            "Premium Customer Segmentation Policy (FY2026)",
            "Canonical rule for Cymbal Retail Malaysia Premium Customers: users.traffic_source='Email' AND users.age>=35 AND >=1 completed order (ord_stat_cd=1). NEVER use deprecated users.legacy_vip_flag.",
            USERS_OVERVIEW_MD,
        ),
        (
            "governed_net_revenue_metric",
            "Governed Net Revenue (MYR) — Certified KPI Formula",
            "Authoritative recognized revenue formula in cymbal_retail_my.orders_raw_v2: SUM(amt_gross_myr - disc_myr) WHERE ord_stat_cd = 1.",
            build_policy_markdown(project_id),
        ),
        (
            "order_status_and_qa_exclusion",
            "Order Status Codes & QA Load-Test Sandbox Exclusion",
            "Defines orders_raw_v2.ord_stat_cd enum values: 1=Completed, 2=Returned, 9=Cancelled, 99=Engineering QA Load-Test Sandbox (exclude from all analytics).",
            ORDERS_OVERVIEW_MD,
        ),
    ]
    for eid, title, desc, md in cs_entries:
        ename = f"{cs_parent}/entries/{eid}"
        entry = dataplex_v1.Entry(
            name=ename,
            entry_type="projects/dataplex-types/locations/global/entryTypes/generic",
            entry_source=dataplex_v1.EntrySource(
                display_name=title,
                description=desc,
                system="KNOWLEDGE_STUDIO",
                location=KC_ENTRY_LOCATION,
            ),
            aspects={
                "dataplex-types.global.generic": _make_generic_aspect(),
                "dataplex-types.global.overview": _make_overview_aspect(md),
            },
        )
        try:
            catalog.get_entry(name=ename)
            catalog.update_entry(entry=entry, update_mask=field_mask_pb2.FieldMask(paths=["entry_source", "aspects"]))
        except gcp_exceptions.NotFound:
            catalog.create_entry(parent=cs_parent, entry_id=eid, entry=entry)
        log.info("Upserted Context Set entry: %s", eid)

    # Link Context Set entries to `@bigquery` table entries so the Studio Context Graph connects them
    users_bq = f"projects/{project_number}/locations/{KC_ENTRY_LOCATION}/entryGroups/@bigquery/entries/bigquery.googleapis.com/projects/{project_id}/datasets/{DATASET_ID}/tables/users"
    orders_bq = f"projects/{project_number}/locations/{KC_ENTRY_LOCATION}/entryGroups/@bigquery/entries/bigquery.googleapis.com/projects/{project_id}/datasets/{DATASET_ID}/tables/orders_raw_v2"
    links = [
        ("link_seg_users", f"{cs_parent}/entries/customer_segmentation_policy", users_bq),
        ("link_seg_orders", f"{cs_parent}/entries/customer_segmentation_policy", orders_bq),
        ("link_rev_orders", f"{cs_parent}/entries/governed_net_revenue_metric", orders_bq),
        ("link_qa_orders", f"{cs_parent}/entries/order_status_and_qa_exclusion", orders_bq),
    ]
    for link_id, src_entry, dst_entry in links:
        link_url = f"{cs_url}/entryLinks/{link_id}"
        try:
            _dataplex_rest("GET", link_url, token, project_id)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                try:
                    _dataplex_rest(
                        "POST",
                        f"{cs_url}/entryLinks?entryLinkId={link_id}",
                        token,
                        project_id,
                        {
                            "entryLinkType": "projects/dataplex-types/locations/global/entryLinkTypes/reference",
                            "entryReferences": [
                                {"name": src_entry, "type": "SOURCE"},
                                {"name": dst_entry, "type": "TARGET"},
                            ],
                        },
                    )
                    log.info("Created Context Graph EntryLink: %s", link_id)
                except urllib.error.HTTPError:
                    log.info("Skipped EntryLink %s (waiting for @bigquery sync)", link_id)


def seed_knowledge_catalog(project_id: str, project_number: str) -> None:
    """Populate Policy EntryGroup, `@bigquery` Overview Aspects, and Business Glossary."""
    catalog = dataplex_v1.CatalogServiceClient(transport="rest")
    policy_md = build_policy_markdown(project_id)

    eg_parent = f"projects/{project_id}/locations/{KC_ENTRY_LOCATION}"
    eg_name = f"{eg_parent}/entryGroups/{POLICY_ENTRY_GROUP_ID}"
    try:
        catalog.get_entry_group(name=eg_name)
    except gcp_exceptions.NotFound:
        op = catalog.create_entry_group(
            parent=eg_parent,
            entry_group_id=POLICY_ENTRY_GROUP_ID,
            entry_group=dataplex_v1.EntryGroup(
                display_name="Cymbal Retail Malaysia — Governed Policies",
                description="Authoritative customer segmentation and net revenue rules for Cymbal Retail Malaysia.",
            ),
        )
        op.result(timeout=60.0)

    policy_entry_name = f"{eg_name}/entries/{POLICY_ENTRY_ID}"
    policy_entry = dataplex_v1.Entry(
        name=policy_entry_name,
        entry_type="projects/dataplex-types/locations/global/entryTypes/generic",
        entry_source=dataplex_v1.EntrySource(
            display_name="Cymbal Malaysia Customer Segmentation & Net Revenue Policy (FY2026)",
            description=(
                "CERTIFIED POLICY: Premium Customer = (users.traffic_source='Email' AND users.age>=35 "
                "AND >=1 ord_stat_cd=1 order; NEVER use deprecated legacy_vip_flag). "
                "Governed Net Revenue = SUM(amt_gross_myr - disc_myr) WHERE ord_stat_cd = 1 "
                "(exclude 2=Returned, 9=Cancelled, 99=QA Load-Test Sandbox)."
            ),
            system="KNOWLEDGE_STUDIO_POLICY",
            location=KC_ENTRY_LOCATION,
            labels={"domain": "cymbal_retail_my", "status": "certified"},
        ),
        aspects={
            "dataplex-types.global.generic": _make_generic_aspect(),
            "dataplex-types.global.overview": _make_overview_aspect(policy_md),
        },
    )
    try:
        catalog.get_entry(name=policy_entry_name)
        catalog.update_entry(entry=policy_entry, update_mask=field_mask_pb2.FieldMask(paths=["entry_source", "aspects"]))
    except gcp_exceptions.NotFound:
        catalog.create_entry(parent=eg_name, entry_id=POLICY_ENTRY_ID, entry=policy_entry)
    log.info("Upserted Policy Entry: %s", policy_entry_name)

    for table_id, overview_md, short_desc in [
        (
            "orders_raw_v2",
            ORDERS_OVERVIEW_MD,
            "Cymbal Malaysia order ledger. Governed Net Revenue = SUM(amt_gross_myr - disc_myr) WHERE ord_stat_cd = 1 (exclude 2=Returned, 9=Cancelled, 99=QA Sandbox).",
        ),
        (
            "users",
            USERS_OVERVIEW_MD,
            "Cymbal Malaysia customer accounts. WARNING: legacy_vip_flag is DEPRECATED (do not use). Canonical Premium Customer = traffic_source='Email' AND age>=35 AND >=1 ord_stat_cd=1 order.",
        ),
    ]:
        bq_entry_name = (
            f"projects/{project_number}/locations/{KC_ENTRY_LOCATION}/entryGroups/@bigquery/"
            f"entries/bigquery.googleapis.com/projects/{project_id}/datasets/{DATASET_ID}/tables/{table_id}"
        )
        for attempt in range(6):
            try:
                catalog.get_entry(name=bq_entry_name)
                catalog.update_entry(
                    entry=dataplex_v1.Entry(
                        name=bq_entry_name,
                        entry_source=dataplex_v1.EntrySource(description=short_desc),
                        aspects={"dataplex-types.global.overview": _make_overview_aspect(overview_md)},
                    ),
                    update_mask=field_mask_pb2.FieldMask(paths=["aspects"]),
                )
                log.info("Attached Knowledge Studio overview aspect to BigQuery table: %s", table_id)
                break
            except gcp_exceptions.NotFound:
                if attempt < 5:
                    time.sleep(3)

    glossary_client = dataplex_v1.BusinessGlossaryServiceClient(transport="rest")
    for glossary_loc in (KC_GLOSSARY_LOCATION, "us", "us-central1"):
        g_parent = f"projects/{project_id}/locations/{glossary_loc}"
        g_name = f"{g_parent}/glossaries/{GLOSSARY_ID}"
        try:
            try:
                glossary_client.get_glossary(name=g_name)
            except gcp_exceptions.NotFound:
                op_g = glossary_client.create_glossary(
                    parent=g_parent,
                    glossary_id=GLOSSARY_ID,
                    glossary=dataplex_v1.Glossary(
                        display_name="Cymbal Retail Malaysia Business Glossary",
                        description="Certified KPI definitions and customer segmentation policies for Cymbal Retail Malaysia (cymbal_retail_my).",
                    ),
                )
                op_g.result(timeout=60.0)

            terms = [
                (
                    "premium_customer",
                    "Premium Customer (Cymbal Malaysia)",
                    "Canonical VIP/Premium segment in cymbal_retail_my: users.traffic_source = 'Email' AND users.age >= 35 AND >= 1 completed order (orders_raw_v2.ord_stat_cd = 1). NEVER use users.legacy_vip_flag.",
                ),
                (
                    "governed_net_revenue",
                    "Governed Net Revenue (MYR)",
                    "Official recognized revenue for Cymbal Retail Malaysia in cymbal_retail_my.orders_raw_v2: SUM(amt_gross_myr - disc_myr) WHERE ord_stat_cd = 1. Excludes returned (2), cancelled (9), and QA sandbox orders (99).",
                ),
                (
                    "qa_sandbox_order_exclusion",
                    "QA Sandbox & Cancelled Order Exclusion (ord_stat_cd)",
                    "In cymbal_retail_my.orders_raw_v2, ord_stat_cd = 99 denotes synthetic engineering load-test rows (RM 420,000 in Q3 2026), 2 = Returned, and 9 = Cancelled. Always filter ord_stat_cd = 1.",
                ),
            ]
            for term_id, display_name, desc in terms:
                t_name = f"{g_name}/terms/{term_id}"
                term_obj = dataplex_v1.GlossaryTerm(
                    name=t_name, parent=g_name, display_name=display_name, description=desc
                )
                try:
                    glossary_client.get_glossary_term(name=t_name)
                    glossary_client.update_glossary_term(
                        term=term_obj,
                        update_mask=field_mask_pb2.FieldMask(paths=["display_name", "description"]),
                    )
                except gcp_exceptions.NotFound:
                    glossary_client.create_glossary_term(parent=g_name, term_id=term_id, term=term_obj)
            log.info("Upserted Business Glossary & 3 governed terms: %s", g_name)
        except gcp_exceptions.GoogleAPICallError as exc:
            if glossary_loc == KC_GLOSSARY_LOCATION:
                raise
            log.info("Skipped optional regional glossary in %s (%s)", glossary_loc, exc)


def verify_seeded_numbers(bq: bigquery.Client, project_id: str) -> None:
    """Assert deterministic Q3 2026 benchmarks match RM 1,280,000.00 vs RM 2,352,500.00."""
    check_sql = f"""
    SELECT
      (
        SELECT ROUND(SUM(o.amt_gross_myr - o.disc_myr), 2)
        FROM `{project_id}.{DATASET_ID}.orders_raw_v2` AS o
        JOIN `{project_id}.{DATASET_ID}.users` AS u ON o.user_id = u.user_id
        WHERE u.traffic_source = 'Email' AND u.age >= 35 AND o.ord_stat_cd = 1
          AND DATE(o.order_ts) BETWEEN '2026-07-01' AND '2026-09-30'
      ) AS governed_q3_net_revenue_myr,
      (
        SELECT ROUND(SUM(o.amt_gross_myr - o.disc_myr), 2)
        FROM `{project_id}.{DATASET_ID}.orders_raw_v2` AS o
        JOIN `{project_id}.{DATASET_ID}.users` AS u ON o.user_id = u.user_id
        WHERE u.legacy_vip_flag = TRUE
          AND DATE(o.order_ts) BETWEEN '2026-07-01' AND '2026-09-30'
      ) AS ungrounded_legacy_vip_myr
    """
    row = next(iter(bq.query(check_sql).result()))
    gov = float(row["governed_q3_net_revenue_myr"])
    naive = float(row["ungrounded_legacy_vip_myr"])
    pct = ((naive - gov) / gov) * 100.0
    log.info(
        "Verified Benchmarks -> Governed Net Revenue: RM %s | Ungrounded Legacy VIP: RM %s (+%.1f%%)",
        f"{gov:,.2f}",
        f"{naive:,.2f}",
        pct,
    )
    if gov != 1280000.0:
        raise RuntimeError(f"Expected governed Q3 Net Revenue RM 1,280,000.00, got {gov}")


def main() -> None:
    project_id = resolve_project_id()
    token = get_oauth_token()
    project_number = resolve_project_number(project_id, token)
    log.info("Seeding demo into GCP Project: %s (projectNumber=%s)", project_id, project_number)

    bq = bigquery.Client(project=project_id, location=BQ_LOCATION)
    seed_bigquery_tables(bq, project_id)
    verify_seeded_numbers(bq, project_id)
    seed_knowledge_catalog(project_id, project_number)
    seed_knowledge_studio_context_set(project_id, project_number, token)
    log.info("Demo seed complete for %s.%s!", project_id, DATASET_ID)


if __name__ == "__main__":
    main()

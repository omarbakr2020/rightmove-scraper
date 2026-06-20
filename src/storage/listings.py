import dataclasses
import json
from typing import Optional, Tuple
import psycopg2
import psycopg2.extras
from ..types import SearchListing, DetailListing, SearchImage, DetailImage


def create_scrape_run(conn, search_region: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scrape_runs (portal, search_region, status) "
            "VALUES ('rightmove', %s, 'running') RETURNING id",
            (search_region,)
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def update_scrape_run(conn, run_id: int, status: str, **counters):
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE scrape_runs SET
               status              = %s,
               finished_at         = NOW(),
               listings_discovered = COALESCE(%s, listings_discovered),
               listings_new        = COALESCE(%s, listings_new),
               listings_updated    = COALESCE(%s, listings_updated),
               listings_unchanged  = COALESCE(%s, listings_unchanged),
               listings_errored    = COALESCE(%s, listings_errored),
               error_message       = %s
               WHERE id = %s""",
            (
                status,
                counters.get('discovered'),
                counters.get('new'),
                counters.get('updated'),
                counters.get('unchanged'),
                counters.get('errored'),
                counters.get('error_message'),
                run_id,
            )
        )
    conn.commit()


def increment_counter(conn, run_id: int, counter: str):
    allowed = {
        'listings_discovered', 'listings_new', 'listings_updated',
        'listings_unchanged', 'listings_errored'
    }
    if counter not in allowed:
        raise ValueError(f'Unknown counter: {counter}')
    with conn.cursor() as cur:
        cur.execute(
            f'UPDATE scrape_runs SET {counter} = {counter} + 1 WHERE id = %s',
            (run_id,)
        )
    conn.commit()


def upsert_listing(
    conn,
    search: SearchListing,
    detail: Optional[DetailListing],
    scrape_run_id: int,
) -> Tuple[int, bool, bool]:
    
    price          = (detail.price if detail else None) or search.price
    price_raw      = detail.price_raw      if detail else None
    price_qualifier = detail.price_qualifier if detail else ''

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO listings (
               portal, portal_listing_id, url,
               price, price_raw, price_qualifier,
               display_address, outcode, incode, full_postcode,
               country_code, uk_country, latitude, longitude,
               property_type, bedrooms, bathrooms, key_features,
               description_html, description_text,
               agent_branch_id, agent_branch_name, agent_branch_display_name,
               agent_company_name, agent_company_trading_name,
               agent_display_address, agent_profile_url, agent_logo_path,
               enc_id, listing_status, scrape_status,
               last_seen_at, last_scraped_at, scrape_run_id, raw_json
             ) VALUES (
               'rightmove', %s, %s,
               %s, %s, %s,
               %s, %s, %s, %s,
               %s, %s, %s, %s,
               %s, %s, %s, %s,
               %s, %s,
               %s, %s, %s,
               %s, %s,
               %s, %s, %s,
               %s, 'published', 'active',
               NOW(), NOW(), %s, %s
             )
             ON CONFLICT (portal, portal_listing_id) DO UPDATE SET
               price            = EXCLUDED.price,
               price_raw        = EXCLUDED.price_raw,
               price_qualifier  = EXCLUDED.price_qualifier,
               display_address  = EXCLUDED.display_address,
               property_type    = EXCLUDED.property_type,
               bedrooms         = EXCLUDED.bedrooms,
               bathrooms        = EXCLUDED.bathrooms,
               key_features     = EXCLUDED.key_features,
               description_html = COALESCE(EXCLUDED.description_html, listings.description_html),
               description_text = COALESCE(EXCLUDED.description_text, listings.description_text),
               agent_branch_id           = EXCLUDED.agent_branch_id,
               agent_branch_display_name = EXCLUDED.agent_branch_display_name,
               agent_company_name = COALESCE(EXCLUDED.agent_company_name, listings.agent_company_name),
               last_seen_at     = NOW(),
               last_scraped_at  = NOW(),
               scrape_run_id    = EXCLUDED.scrape_run_id,
               raw_json         = EXCLUDED.raw_json
             RETURNING id, price, (xmax = 0) AS is_new""",
            (
                search.id,
                search.url,
                price,
                price_raw,
                price_qualifier,
                search.display_address,
                detail.outcode    if detail else None,
                detail.incode     if detail else None,
                detail.full_postcode if detail else None,
                detail.country_code  if detail else None,
                detail.uk_country    if detail else None,
                (detail.latitude  if detail else None) or search.latitude,
                (detail.longitude if detail else None) or search.longitude,
                search.property_sub_type or (detail.property_sub_type if detail else None),
                search.bedrooms  or (detail.bedrooms  if detail else None),
                search.bathrooms or (detail.bathrooms if detail else None),
                search.key_features, 
                detail.description_html if detail else None,
                detail.description_text if detail else None,
                search.agent_branch_id,
                search.agent_branch_name,
                search.agent_branch_display_name,
                detail.agent_company_name        if detail else None,
                detail.agent_company_trading_name if detail else None,
                detail.agent_display_address     if detail else None,
                detail.agent_profile_url         if detail else None,
                detail.agent_logo_path           if detail else None,
                detail.enc_id if detail else None,
                scrape_run_id,
                psycopg2.extras.Json({
                    'search': dataclasses.asdict(search),
                    'detail': dataclasses.asdict(detail) if detail else None,
                }),
            )
        )

        row = cur.fetchone()
        listing_id, previous_price, is_new = row[0], row[1], bool(row[2])

        price_changed = False
        if price is not None:
            if is_new:
                
                cur.execute(
                    """INSERT INTO price_history
                       (listing_id, price, price_raw, price_qualifier, change_type, scrape_run_id)
                       VALUES (%s, %s, %s, %s, 'initial', %s)""",
                    (listing_id, price, price_raw, price_qualifier, scrape_run_id)
                )
            elif previous_price is not None and price != previous_price:
                change_type = 'reduction' if price < previous_price else 'increase'
                cur.execute(
                    """INSERT INTO price_history
                       (listing_id, price, price_raw, price_qualifier, change_type, scrape_run_id)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (listing_id, price, price_raw, price_qualifier, change_type, scrape_run_id)
                )
                price_changed = True

        
        images = detail.images if (detail and detail.images) else _promote_search_images(search.images)

        for img in images:
            if not img.url_base:
                continue
            base = img.url_base
            url_large     = img.url_large     or f'https://media.rightmove.co.uk/dir/{base}_max_656x437.jpeg'
            url_medium    = img.url_medium    or f'https://media.rightmove.co.uk/dir/{base}_max_476x317.jpeg'
            url_thumbnail = img.url_thumbnail or f'https://media.rightmove.co.uk/dir/{base}_max_135x100.jpeg'

            cur.execute(
                """INSERT INTO listing_images
                   (listing_id, position, url_original, url_large, url_medium, url_thumbnail, caption)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (listing_id, position) DO UPDATE SET
                     url_large     = EXCLUDED.url_large,
                     url_medium    = EXCLUDED.url_medium,
                     url_thumbnail = EXCLUDED.url_thumbnail,
                     caption       = EXCLUDED.caption""",
                (listing_id, img.position, base, url_large, url_medium, url_thumbnail, img.caption)
            )

    conn.commit()
    return listing_id, is_new, price_changed


def _promote_search_images(search_images: list) -> list:
    return [
        DetailImage(
            position=img.position,
            url_base=img.url_base,
            url_large=None,
            url_medium=None,
            url_thumbnail=None,
            caption=img.caption,
        )
        for img in search_images
    ]

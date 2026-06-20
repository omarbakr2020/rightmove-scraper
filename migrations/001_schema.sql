
CREATE TABLE IF NOT EXISTS scrape_runs (
    id                  BIGSERIAL       PRIMARY KEY,
    portal              VARCHAR(50)     NOT NULL DEFAULT 'rightmove',
    search_region       VARCHAR(100),                          
    started_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              VARCHAR(20)     NOT NULL DEFAULT 'running',
                                                               
    listings_discovered INTEGER         NOT NULL DEFAULT 0,
    listings_new        INTEGER         NOT NULL DEFAULT 0,
    listings_updated    INTEGER         NOT NULL DEFAULT 0,
    listings_unchanged  INTEGER         NOT NULL DEFAULT 0,
    listings_errored    INTEGER         NOT NULL DEFAULT 0,
    error_message       TEXT,
    metadata            JSONB                                  
);

CREATE TABLE IF NOT EXISTS listings (
    id                          BIGSERIAL   PRIMARY KEY,
    portal                      VARCHAR(50) NOT NULL DEFAULT 'rightmove',
    portal_listing_id           VARCHAR(50) NOT NULL,
    url                         TEXT        NOT NULL,
    enc_id                      TEXT,

    listing_status              VARCHAR(30),                   
    scrape_status               VARCHAR(20) NOT NULL DEFAULT 'active',
                                                              
    first_seen_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_scraped_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scrape_run_id               BIGINT      REFERENCES scrape_runs(id),

    price                       INTEGER,                       
    price_raw                   VARCHAR(100),                  
    price_qualifier             VARCHAR(100) DEFAULT '',       

    display_address             TEXT,
    outcode                     VARCHAR(10),                   
    incode                      VARCHAR(10),                   
    full_postcode               VARCHAR(15),                  
    country_code                VARCHAR(5),                   
    uk_country                  VARCHAR(50),                  
    latitude                    NUMERIC(10, 7),
    longitude                   NUMERIC(10, 7),

    property_type               VARCHAR(100),                  
    bedrooms                    SMALLINT,
    bathrooms                   SMALLINT,
    key_features                TEXT[],                      

    description_html            TEXT,
    description_text            TEXT,

    agent_branch_id             INTEGER,
    agent_branch_name           TEXT,
    agent_branch_display_name   TEXT,
    agent_company_name          TEXT,
    agent_company_trading_name  TEXT,
    agent_display_address       TEXT,
    agent_profile_url           TEXT,
    agent_logo_path             TEXT,

    
    raw_json                    JSONB,

    CONSTRAINT uq_portal_listing UNIQUE (portal, portal_listing_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_outcode        ON listings(outcode);
CREATE INDEX IF NOT EXISTS idx_listings_price          ON listings(price);
CREATE INDEX IF NOT EXISTS idx_listings_bedrooms       ON listings(bedrooms);
CREATE INDEX IF NOT EXISTS idx_listings_property_type  ON listings(property_type);
CREATE INDEX IF NOT EXISTS idx_listings_scrape_status  ON listings(scrape_status);
CREATE INDEX IF NOT EXISTS idx_listings_last_scraped   ON listings(last_scraped_at);
CREATE INDEX IF NOT EXISTS idx_listings_agent_branch   ON listings(agent_branch_id);
CREATE INDEX IF NOT EXISTS idx_listings_postcode       ON listings(full_postcode);


CREATE TABLE IF NOT EXISTS price_history (
    id              BIGSERIAL   PRIMARY KEY,
    listing_id      BIGINT      NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price           INTEGER     NOT NULL,                      
    price_raw       VARCHAR(100),
    price_qualifier VARCHAR(100),
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scrape_run_id   BIGINT      REFERENCES scrape_runs(id),
    change_type     VARCHAR(20)                                
);

CREATE INDEX IF NOT EXISTS idx_price_history_listing  ON price_history(listing_id);
CREATE INDEX IF NOT EXISTS idx_price_history_observed ON price_history(observed_at);
CREATE INDEX IF NOT EXISTS idx_price_history_type     ON price_history(change_type);


CREATE TABLE IF NOT EXISTS listing_images (
    id              BIGSERIAL   PRIMARY KEY,
    listing_id      BIGINT      NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    position        SMALLINT    NOT NULL,                      
    url_original    TEXT        NOT NULL,                     
    url_thumbnail   TEXT,                                      
    url_medium      TEXT,                                      
    url_large       TEXT,                                      
    caption         TEXT,

    CONSTRAINT uq_listing_image UNIQUE (listing_id, position)
);

CREATE INDEX IF NOT EXISTS idx_images_listing ON listing_images(listing_id);

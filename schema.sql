-- =============================================================
-- BFA Scouting & Evaluation System
-- PostgreSQL Schema v1.0
-- Target: PostgreSQL 15+
-- =============================================================
-- This file is idempotent-friendly when paired with init_db.py
-- which drops/recreates in dev. For production, use Alembic.
-- =============================================================

-- =============================================================
-- 1. AUTH & USERS
-- =============================================================
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    full_name       VARCHAR(255) NOT NULL,
    full_name_ar    VARCHAR(255),
    role            VARCHAR(32)  NOT NULL
                    -- Phase 7: 'nt_staff' added. Constraint widened additively;
                    -- the 4 original roles remain so existing decorators
                    -- (admin_or_td_required, any_authenticated, ...) keep working.
                    -- Youth NT: 'youth_nt' added — the first RESTRICTED role
                    -- (sees ONLY youth players). Additive, again.
                    CHECK (role IN ('admin','technical_director','scout','viewer','nt_staff','youth_nt')),
    phone           VARCHAR(32),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_email  ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role   ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);


-- =============================================================
-- 2. POSITION TAXONOMY
--    8 position groups → many Wyscout positions
-- =============================================================
CREATE TABLE IF NOT EXISTS position_groups (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(8)   NOT NULL UNIQUE,
    name_en     VARCHAR(64)  NOT NULL,
    name_ar     VARCHAR(64)  NOT NULL,
    description TEXT,
    sort_order  INTEGER      NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS positions (
    id                SERIAL PRIMARY KEY,
    code              VARCHAR(16) NOT NULL UNIQUE,   -- Wyscout code (LCMF, RCMF3, etc.)
    name              VARCHAR(64) NOT NULL,
    position_group_id INTEGER     NOT NULL REFERENCES position_groups(id),
    sort_order        INTEGER     NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_positions_group ON positions(position_group_id);


-- =============================================================
-- 2b. CLUBS (Phase 5c-3)
--     Bahraini league registry. Players reference via club_id; the
--     denormalised text in players.current_club survives for non-Bahraini
--     clubs (when club_id IS NULL).
-- =============================================================
CREATE TABLE IF NOT EXISTS clubs (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    division    VARCHAR(16)  NOT NULL
                CHECK (division IN ('premier', 'first')),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (name, division)
);
CREATE INDEX IF NOT EXISTS idx_clubs_division ON clubs(division);
CREATE INDEX IF NOT EXISTS idx_clubs_active   ON clubs(is_active);


-- =============================================================
-- 3. PLAYERS
-- =============================================================
CREATE TABLE IF NOT EXISTS players (
    id                     SERIAL PRIMARY KEY,
    full_name              VARCHAR(255) NOT NULL,
    full_name_ar           VARCHAR(255),
    national_id            VARCHAR(32)  UNIQUE,        -- CPR, TEXT to preserve leading zeros
    dob                    DATE,
    nationality            VARCHAR(64),
    foot                   VARCHAR(8)
                           CHECK (foot IN ('left','right','both') OR foot IS NULL),
    height_cm              INTEGER,
    weight_kg              INTEGER,
    primary_position_id    INTEGER REFERENCES positions(id),
    secondary_position_id  INTEGER REFERENCES positions(id),
    current_club           VARCHAR(128),
    contract_until         DATE,
    photo_path             VARCHAR(255),
    wyscout_player_id      VARCHAR(64) UNIQUE,
    notes                  TEXT,
    -- National-team eligibility (Phase 5c-1, admin-set, no auto-compute)
    nationality_status     VARCHAR(32)
                           CHECK (nationality_status IN
                               ('bahraini','foreign_ancestry','foreign_residency',
                                'not_eligible','unknown')
                               OR nationality_status IS NULL),
    eligible_from_date     DATE,
    eligibility_notes_admin TEXT,
    -- Bahrain-residency tracking (Phase 5c-2, admin-set, source for 5-year
    -- suggested-eligibility-date UX in players/edit; no auto-compute)
    bahrain_residency_start_date DATE,
    bahrain_residency_notes      TEXT,
    -- Structured nationality + club (Phase 5c-3). nationality_code is ISO
    -- 3166-1 alpha-3; club_id is FK to clubs ON DELETE SET NULL. Free-text
    -- `current_club` is kept as a denormalised cache for non-Bahraini clubs
    -- (when club_id IS NULL).
    nationality_code       CHAR(3),
    -- Passport holders (naturalized Bahrainis). A passport holder is
    -- DEFINED by nationality_status='bahraini' AND origin_country set — no
    -- boolean flag. origin_country is real queryable data (origin-based
    -- analysis); origin_country_code is the ISO alpha-3 for the flag.
    origin_country         VARCHAR(64),
    origin_country_code    CHAR(3),
    club_id                INTEGER REFERENCES clubs(id) ON DELETE SET NULL,
    -- Youth NT: squad age-group. UPPERCASE values (distinct from
    -- matches.age_group which is lowercase and means the match level).
    -- DEFAULT 'senior' keeps new players on the general list unless
    -- explicitly created inside a youth sub-view. NULL is tolerated
    -- (treated as senior by the youth-exclusion filter).
    age_group              VARCHAR(16) DEFAULT 'senior'
                           CHECK (age_group IS NULL OR
                                  age_group IN ('U17','U20','U23','senior')),
    is_active              BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by             INTEGER REFERENCES users(id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_players_name        ON players(full_name);
CREATE INDEX IF NOT EXISTS idx_players_position    ON players(primary_position_id);
CREATE INDEX IF NOT EXISTS idx_players_national_id ON players(national_id);
CREATE INDEX IF NOT EXISTS idx_players_active      ON players(is_active);
CREATE INDEX IF NOT EXISTS idx_players_nationality ON players(nationality_code);
CREATE INDEX IF NOT EXISTS idx_players_origin_country ON players(origin_country) WHERE origin_country IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_players_club_id     ON players(club_id);
CREATE INDEX IF NOT EXISTS idx_players_age_group   ON players(age_group);


-- =============================================================
-- 4. EVALUATION CRITERIA CONFIG (admin-editable)
-- =============================================================
CREATE TABLE IF NOT EXISTS criteria_categories (
    id         SERIAL PRIMARY KEY,
    code       VARCHAR(32) NOT NULL UNIQUE,
    name_en    VARCHAR(64) NOT NULL,
    name_ar    VARCHAR(64) NOT NULL,
    color_hex  VARCHAR(7),                   -- for radar chart slices
    sort_order INTEGER     NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS criteria (
    id          SERIAL PRIMARY KEY,
    category_id INTEGER     NOT NULL REFERENCES criteria_categories(id) ON DELETE RESTRICT,
    code        VARCHAR(64) NOT NULL UNIQUE,
    name_en     VARCHAR(128) NOT NULL,
    name_ar     VARCHAR(128) NOT NULL,
    description TEXT,
    scale_min   INTEGER     NOT NULL DEFAULT 1,
    scale_max   INTEGER     NOT NULL DEFAULT 10,
    allow_half  BOOLEAN     NOT NULL DEFAULT TRUE,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    sort_order  INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (scale_max > scale_min)
);
CREATE INDEX IF NOT EXISTS idx_criteria_category ON criteria(category_id);
CREATE INDEX IF NOT EXISTS idx_criteria_active   ON criteria(is_active);

-- Maps which criteria appear for which position group (the dynamic-form key)
CREATE TABLE IF NOT EXISTS position_group_criteria (
    position_group_id INTEGER       NOT NULL REFERENCES position_groups(id) ON DELETE CASCADE,
    criterion_id      INTEGER       NOT NULL REFERENCES criteria(id) ON DELETE CASCADE,
    weight            NUMERIC(4,2)  NOT NULL DEFAULT 1.0,
    sort_order        INTEGER       NOT NULL DEFAULT 0,
    PRIMARY KEY (position_group_id, criterion_id)
);
CREATE INDEX IF NOT EXISTS idx_pgc_group ON position_group_criteria(position_group_id);


-- =============================================================
-- 5. EVALUATIONS
-- =============================================================
CREATE TABLE IF NOT EXISTS evaluations (
    id                  SERIAL PRIMARY KEY,
    player_id           INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    evaluator_id        INTEGER NOT NULL REFERENCES users(id)   ON DELETE RESTRICT,
    position_group_id   INTEGER NOT NULL REFERENCES position_groups(id),
    position_played_id  INTEGER REFERENCES positions(id),

    -- match context (nullable: supports freestanding evals)
    -- match_id (Phase 5c-1) is the canonical link; match_label/_date/competition
    -- are legacy text fallbacks for evals not tied to a matches row.
    match_id            INTEGER,  -- FK added below after matches table: REFERENCES matches(id)
    match_label         VARCHAR(255),
    match_date          DATE,
    competition         VARCHAR(128),
    minutes_observed    INTEGER,

    overall_rating      NUMERIC(4,2),
    summary             TEXT,
    recommendation      VARCHAR(32)
                        CHECK (recommendation IN
                            ('call_up','shortlist','monitor','not_at_level','release')
                            OR recommendation IS NULL),
    status              VARCHAR(16) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','submitted','locked')),

    -- National-team readiness section (Phase 5a)
    nt_readiness_level  VARCHAR(16)
                        CHECK (nt_readiness_level IN
                            ('senior','u23','u20','u17','not_ready')
                            OR nt_readiness_level IS NULL),
    eligibility_status  VARCHAR(32)
                        CHECK (eligibility_status IN
                            ('bahraini','foreign_residency','foreign_ancestry',
                             'foreign_other','not_eligible','unknown')
                            OR eligibility_status IS NULL),
    eligibility_notes   TEXT,
    comparable_player   VARCHAR(255),

    submitted_at        TIMESTAMPTZ,
    -- Lock workflow (Phase 5c-2): admin/TD locks submitted evals;
    -- locked_reason is required (>= 10 chars) on the unlock path.
    locked_at           TIMESTAMPTZ,
    locked_by           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    locked_reason       TEXT,
    -- Admin direct-edit tracking (Phase 5c-2): preserves original evaluator_id
    -- but records who last touched it. UI shows an "edited by admin" badge.
    last_edited_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_edited_at      TIMESTAMPTZ,
    -- Soft-delete trio (Phase 5c-3). EVERY user-facing read query MUST
    -- filter `WHERE deleted_at IS NULL` (admin recovery page is the only
    -- documented exception). The CHECK enforces all-three-or-none with a
    -- minimum 10-char reason — no half-deleted state possible.
    deleted_at          TIMESTAMPTZ,
    deleted_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    deleted_reason      TEXT,
    -- Phase 7: role the creator had at the time the evaluation was
    -- authored. Drives the NT VISIBILITY INVARIANT: every read query
    -- in app/evaluations/helpers.py MUST filter
    -- `AND created_by_role != 'nt_staff'` when the requesting user is
    -- a scout (NT scratchpad is admin/nt_staff/TD only).
    created_by_role     VARCHAR(32) NOT NULL DEFAULT 'scout',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT evaluations_soft_delete_consistency
        CHECK ((deleted_at IS NULL  AND deleted_by IS NULL  AND deleted_reason IS NULL)
            OR (deleted_at IS NOT NULL AND deleted_by IS NOT NULL
                AND deleted_reason IS NOT NULL AND char_length(deleted_reason) >= 10))
);
CREATE INDEX IF NOT EXISTS idx_eval_player          ON evaluations(player_id);
CREATE INDEX IF NOT EXISTS idx_eval_evaluator       ON evaluations(evaluator_id);
CREATE INDEX IF NOT EXISTS idx_eval_status          ON evaluations(status);
CREATE INDEX IF NOT EXISTS idx_eval_match_date      ON evaluations(match_date);
CREATE INDEX IF NOT EXISTS idx_evaluations_match_id ON evaluations(match_id);
CREATE INDEX IF NOT EXISTS idx_eval_last_edited_by  ON evaluations(last_edited_by);
CREATE INDEX IF NOT EXISTS idx_evaluations_deleted_at ON evaluations(deleted_at);
CREATE INDEX IF NOT EXISTS idx_evaluations_created_by_role ON evaluations(created_by_role);  -- Phase 7

CREATE TABLE IF NOT EXISTS evaluation_scores (
    id                SERIAL PRIMARY KEY,
    evaluation_id     INTEGER      NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    criterion_id      INTEGER      NOT NULL REFERENCES criteria(id)   ON DELETE RESTRICT,
    -- Tri-state (Phase 5c-1.1): score is either a real value, or NULL when
    -- the criterion was explicitly marked "not applicable" by the scout.
    -- Untouched criteria have NO row at all (absence is the third state).
    score             NUMERIC(4,2),
    is_not_applicable BOOLEAN      NOT NULL DEFAULT FALSE,
    comment           TEXT,
    UNIQUE (evaluation_id, criterion_id),
    CONSTRAINT evaluation_scores_score_or_na
        CHECK ((score IS NOT NULL AND is_not_applicable = FALSE)
            OR (score IS NULL     AND is_not_applicable = TRUE))
);
CREATE INDEX IF NOT EXISTS idx_eval_scores_eval      ON evaluation_scores(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_eval_scores_criterion ON evaluation_scores(criterion_id);


-- =============================================================
-- 6. MATCHES (Phase 5b)
--    Central record of every match a player participated in —
--    Wyscout-tracked OR purely scout-observed. Created by either
--    the Wyscout ingest auto-link or (Phase 5c) the evaluation form.
-- =============================================================
CREATE TABLE IF NOT EXISTS matches (
    id              SERIAL PRIMARY KEY,
    match_date      DATE         NOT NULL,
    home_team       VARCHAR(128) NOT NULL,
    away_team       VARCHAR(128) NOT NULL,
    home_score      INTEGER,
    away_score      INTEGER,
    competition     VARCHAR(128),
    age_group       VARCHAR(16)
                    CHECK (age_group IN ('senior','u23','u20','u17') OR age_group IS NULL),
    match_type      VARCHAR(32)
                    CHECK (match_type IN ('league','cup','friendly','tournament','national_team') OR match_type IS NULL),
    bfa_team_side   VARCHAR(8)
                    CHECK (bfa_team_side IN ('home','away') OR bfa_team_side IS NULL),
    notes           TEXT,
    source          VARCHAR(16) NOT NULL DEFAULT 'manual'
                    CHECK (source IN ('wyscout','manual')),
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Match identity per locked decision: date + raw teams unique.
    -- Case-insensitive dedup happens in the auto-link query (idx below).
    UNIQUE (match_date, home_team, away_team)
);
CREATE INDEX IF NOT EXISTS idx_matches_lookup
    ON matches (match_date, LOWER(BTRIM(home_team)), LOWER(BTRIM(away_team)));
CREATE INDEX IF NOT EXISTS idx_matches_age_group ON matches (age_group);
CREATE INDEX IF NOT EXISTS idx_matches_source    ON matches (source);
CREATE INDEX IF NOT EXISTS idx_matches_date      ON matches (match_date);

-- Deferred FK: evaluations.match_id → matches.id
-- (evaluations is defined before matches, so FK must be added here)
ALTER TABLE evaluations
    ADD CONSTRAINT IF NOT EXISTS fk_evaluations_match_id
    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE SET NULL;


-- =============================================================
-- 7. WYSCOUT INTEGRATION
-- =============================================================
CREATE TABLE IF NOT EXISTS wyscout_imports (
    id            SERIAL PRIMARY KEY,
    uploaded_by   INTEGER     NOT NULL REFERENCES users(id),
    file_name     VARCHAR(255) NOT NULL,
    player_id     INTEGER REFERENCES players(id) ON DELETE SET NULL,
    row_count     INTEGER     NOT NULL DEFAULT 0,
    status        VARCHAR(16) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','success','failed')),
    error_message TEXT,
    imported_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wyscout_match_stats (
    id                          SERIAL PRIMARY KEY,
    player_id                   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    import_id                   INTEGER REFERENCES wyscout_imports(id) ON DELETE SET NULL,
    -- Auto-linked by Wyscout ingest to a matches.id row (Phase 5b).
    -- ON DELETE SET NULL preserves stat history if a match is deleted.
    match_id                    INTEGER REFERENCES matches(id) ON DELETE SET NULL,

    -- match identity (parsed from the "Match" column)
    match_label                 VARCHAR(255) NOT NULL,
    competition                 VARCHAR(128),
    match_date                  DATE NOT NULL,
    -- Phase 4.2: BPL season label (Aug-May), e.g. '2025-26'. Derived
    -- from match_date at ingest via app.wyscout.season.derive_season.
    -- Nullable defensively even though match_date is NOT NULL today,
    -- so future ingest paths that pass through NULL dates don't fail.
    season                      VARCHAR(7),
    home_team                   VARCHAR(128),
    away_team                   VARCHAR(128),
    home_score                  INTEGER,
    away_score                  INTEGER,
    is_home                     BOOLEAN,

    -- player context for this match
    position_raw                VARCHAR(64),     -- "LCMF, RCMF" verbatim from Wyscout
    position_primary_id         INTEGER REFERENCES positions(id),
    minutes_played              INTEGER,

    -- aggregate
    total_actions               INTEGER,
    total_actions_successful    INTEGER,

    -- attacking
    goals                       INTEGER,
    assists                     INTEGER,
    shots                       INTEGER,
    shots_on_target             INTEGER,
    xg                          NUMERIC(5,2),
    shot_assists                INTEGER,
    touches_in_box              INTEGER,
    offsides                    INTEGER,
    progressive_runs            INTEGER,

    -- passing
    passes                      INTEGER,
    passes_accurate             INTEGER,
    long_passes                 INTEGER,
    long_passes_accurate        INTEGER,
    crosses                     INTEGER,
    crosses_accurate            INTEGER,
    through_passes              INTEGER,
    through_passes_accurate     INTEGER,

    -- dribbling
    dribbles                    INTEGER,
    dribbles_successful         INTEGER,

    -- duels
    duels                       INTEGER,
    duels_won                   INTEGER,
    aerial_duels                INTEGER,
    aerial_duels_won            INTEGER,
    defensive_duels             INTEGER,
    defensive_duels_won         INTEGER,
    offensive_duels             INTEGER,
    offensive_duels_won         INTEGER,
    loose_ball_duels            INTEGER,
    loose_ball_duels_won        INTEGER,

    -- defending
    interceptions               INTEGER,
    sliding_tackles             INTEGER,
    sliding_tackles_successful  INTEGER,
    clearances                  INTEGER,
    recoveries_opp_half         INTEGER,
    losses_own_half             INTEGER,

    -- discipline
    fouls                       INTEGER,
    fouls_suffered              INTEGER,
    yellow_cards                INTEGER,
    red_cards                   INTEGER,

    -- preserve original row for re-parse / new metrics
    raw_row                     JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (player_id, match_label, match_date)
);
CREATE INDEX IF NOT EXISTS idx_wyscout_player      ON wyscout_match_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_wyscout_date        ON wyscout_match_stats(match_date);
CREATE INDEX IF NOT EXISTS idx_wyscout_competition ON wyscout_match_stats(competition);
CREATE INDEX IF NOT EXISTS idx_wyscout_match_id    ON wyscout_match_stats(match_id);
CREATE INDEX IF NOT EXISTS idx_wyscout_match_stats_season ON wyscout_match_stats(season);  -- Phase 4.2


-- =============================================================
-- 8. AI ARTIFACTS (Gemini outputs cached for re-use)
-- =============================================================
CREATE TABLE IF NOT EXISTS ai_artifacts (
    id             SERIAL PRIMARY KEY,
    artifact_type  VARCHAR(32) NOT NULL
                   CHECK (artifact_type IN
                       ('narrative_en','narrative_ar','comparison',
                        'transcription','consensus_summary')),
    player_id      INTEGER REFERENCES players(id) ON DELETE CASCADE,
    evaluation_id  INTEGER REFERENCES evaluations(id) ON DELETE CASCADE,
    prompt_used    TEXT,
    response       TEXT NOT NULL,
    model_name     VARCHAR(64),
    tokens_used    INTEGER,
    generated_by   INTEGER REFERENCES users(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_player ON ai_artifacts(player_id);
CREATE INDEX IF NOT EXISTS idx_ai_eval   ON ai_artifacts(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_ai_type   ON ai_artifacts(artifact_type);


-- =============================================================
-- 8. AUDIT LOG
-- =============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id   INTEGER,
    details     JSONB,
    ip_address  VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_user    ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity  ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);


-- =============================================================
-- Youth shortlist — tracked youth prospects (flat watchlist)
-- =============================================================
-- One row per shortlisted player (UNIQUE player_id → "add" is idempotent;
-- the route does ON CONFLICT … DO UPDATE to refresh the note). Players are
-- added only while youth (U17/U20/U23) but KEPT after promotion to senior
-- (manual remove only) — a tracked prospect who made it.
CREATE TABLE IF NOT EXISTS youth_shortlist (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    note        TEXT,
    added_by    INTEGER REFERENCES users(id),
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (player_id)
);
CREATE INDEX IF NOT EXISTS idx_youth_shortlist_player ON youth_shortlist(player_id);


-- =============================================================
-- SEED DATA
-- =============================================================

-- Bahraini clubs (Phase 5c-3): 12 Premier + 12 First Division
INSERT INTO clubs (name, division) VALUES
    ('Al-Muharraq',       'premier'),
    ('Al-Khalidiya',      'premier'),
    ('Al-Hidd',           'premier'),
    ('Malkiya Club',      'premier'),
    ('Al-Riffa',          'premier'),
    ('A''Ali FC',         'premier'),
    ('Sitra Club',        'premier'),
    ('Al-Budaiya',        'premier'),
    ('Al-Shabab Manama',  'premier'),
    ('Al-Najma',          'premier'),
    ('Al-Ahli Manama',    'premier'),
    ('Al-Bahrain SC',     'premier'),
    ('Al-Ittifaq',        'first'),
    ('East Riffa',        'first'),
    ('Manama Club',       'first'),
    ('Al-Ettihad',        'first'),
    ('Al-Hala',           'first'),
    ('Um Alhassam',       'first'),
    ('Bouri',             'first'),
    ('Busaiteen',         'first'),
    ('Isa Town',          'first'),
    ('Etehad Alreef',     'first'),
    ('Al-Tadhamun',       'first'),
    ('Galali',            'first')
ON CONFLICT (name, division) DO NOTHING;

-- Position groups (8 buckets)
INSERT INTO position_groups (code, name_en, name_ar, sort_order, description) VALUES
    ('GK', 'Goalkeeper',                'حارس مرمى',   10, 'Shot-stopping, distribution, command of area'),
    ('CB', 'Centre Back',               'قلب دفاع',     20, 'Central defensive duties, aerial dominance'),
    ('FB', 'Full Back / Wing Back',     'ظهير',         30, 'Wide defenders, overlapping support'),
    ('DM', 'Defensive Midfielder',      'وسط دفاعي',    40, 'Screening defence, ball recovery'),
    ('CM', 'Central Midfielder',        'وسط',          50, 'Box-to-box, distribution, transition'),
    ('AM', 'Attacking Midfielder',      'صانع ألعاب',   60, 'Creativity, final-third entries'),
    ('W',  'Winger',                    'جناح',         70, '1v1 wide attackers, crossing, cutting in'),
    ('ST', 'Striker',                   'مهاجم',        80, 'Goal-scoring, hold-up play, finishing')
ON CONFLICT (code) DO NOTHING;

-- Wyscout position codes mapped to position groups
INSERT INTO positions (code, name, position_group_id, sort_order)
SELECT v.code, v.name, pg.id, v.sort_order
FROM (VALUES
    -- GK
    ('GK',    'Goalkeeper',                  'GK', 10),
    -- CB
    ('CB',    'Centre Back',                 'CB', 20),
    ('LCB',   'Left Centre Back',            'CB', 21),
    ('RCB',   'Right Centre Back',           'CB', 22),
    ('LCB3',  'Left Centre Back (3-CB)',     'CB', 23),
    ('RCB3',  'Right Centre Back (3-CB)',    'CB', 24),
    -- FB
    ('LB',    'Left Back',                   'FB', 30),
    ('RB',    'Right Back',                  'FB', 31),
    ('LWB',   'Left Wing Back',              'FB', 32),
    ('RWB',   'Right Wing Back',             'FB', 33),
    -- DM
    ('DMF',   'Defensive Midfielder',        'DM', 40),
    ('LDMF',  'Left Defensive Midfielder',   'DM', 41),
    ('RDMF',  'Right Defensive Midfielder',  'DM', 42),
    -- CM
    ('LCMF',  'Left Central Midfielder',     'CM', 50),
    ('RCMF',  'Right Central Midfielder',    'CM', 51),
    ('LCMF3', 'Left Central Mid (3-MF)',     'CM', 52),
    ('RCMF3', 'Right Central Mid (3-MF)',    'CM', 53),
    -- AM
    ('AMF',   'Attacking Midfielder',        'AM', 60),
    ('LAMF',  'Left Attacking Midfielder',   'AM', 61),
    ('RAMF',  'Right Attacking Midfielder',  'AM', 62),
    -- W
    ('LW',    'Left Winger',                 'W',  70),
    ('RW',    'Right Winger',                'W',  71),
    ('LWF',   'Left Wing Forward',           'W',  72),
    ('RWF',   'Right Wing Forward',          'W',  73),
    -- ST
    ('CF',    'Centre Forward',              'ST', 80),
    ('ST',    'Striker',                     'ST', 81)
) AS v(code, name, grp, sort_order)
JOIN position_groups pg ON pg.code = v.grp
ON CONFLICT (code) DO NOTHING;

-- Criteria categories (4)
INSERT INTO criteria_categories (code, name_en, name_ar, color_hex, sort_order) VALUES
    ('TECH', 'Technical', 'فني',     '#C8102E', 10),
    ('TACT', 'Tactical',  'تكتيكي',  '#B5924C', 20),
    ('PHYS', 'Physical',  'بدني',    '#3B82F6', 30),
    ('MENT', 'Mental',    'ذهني',    '#10B981', 40)
ON CONFLICT (code) DO NOTHING;

-- v0.5.0a — Phase 5a taxonomy (55 items, 303 mappings).
-- Source of truth: migrations/_generate_phase_5a.py
-- Per-position totals: GK=24, CB=42, FB=42, DM=40, CM=37, AM=42, W=38, ST=38
INSERT INTO criteria (category_id, code, name_en, name_ar, sort_order)
SELECT cc.id, v.code, v.name_en, v.name_ar, v.sort_order
FROM (VALUES
    -- TECH
    ('TECH', 'tech_first_touch'              , 'First touch quality (under pressure & in space)'                     , 'جودة استلام الكرة'                           ,  101),
    ('TECH', 'tech_passing_short'            , 'Short passing — accuracy & weight'                                   , 'التمرير القصير'                              ,  102),
    ('TECH', 'tech_passing_long'             , 'Long passing — range & accuracy'                                     , 'التمرير الطويل'                              ,  103),
    ('TECH', 'tech_passing_press'            , 'Passing under defensive pressure'                                    , 'التمرير تحت الضغط'                           ,  104),
    ('TECH', 'tech_passing_progressive'      , 'Vertical / progressive passing selection'                            , 'التمرير التقدمي'                             ,  105),
    ('TECH', 'tech_crossing'                 , 'Crossing — quality & consistency'                                    , 'جودة العرضيات'                               ,  106),
    ('TECH', 'tech_finishing'                , 'Finishing — both feet, composure in box'                             , 'التهديف'                                     ,  107),
    ('TECH', 'tech_finishing_chances'        , 'Conversion of half-chances vs. clear-cut'                            , 'استغلال الفرص'                               ,  108),
    ('TECH', 'tech_dribbling_1v1'            , '1v1 dribbling — functional (not just attempted)'                     , 'المراوغة الفعالة'                            ,  109),
    ('TECH', 'tech_dribbling_press'          , 'Carrying ball under pressure'                                        , 'التحكم تحت الضغط أثناء التقدم'               ,  110),
    ('TECH', 'tech_set_pieces_taking'        , 'Set-piece delivery quality (corners/free-kicks)'                     , 'تنفيذ الكرات الثابتة'                        ,  111),
    ('TECH', 'tech_set_pieces_attacking'     , 'Attacking set-pieces (heading/finishing in box)'                     , 'الكرات الثابتة الهجومية'                     ,  112),
    ('TECH', 'tech_heading_offensive'        , 'Aerial — offensive (attacking corners, crosses)'                     , 'الضربات الرأسية الهجومية'                    ,  113),
    ('TECH', 'tech_heading_defensive'        , 'Aerial — defensive (clearing crosses, set-piece defending)'          , 'الضربات الرأسية الدفاعية'                    ,  114),
    ('TECH', 'tech_ball_striking'            , 'Ball striking — distance shooting, free-kicks'                       , 'جودة التسديد'                                ,  115),
    ('TECH', 'tech_gk_shot_stopping'         , 'Shot stopping — reactions, positioning, handling'                    , 'التصدي'                                      ,  116),
    ('TECH', 'tech_gk_handling'              , 'Handling under pressure (catches, parries, drops)'                   , 'الإمساك بالكرة'                              ,  117),
    ('TECH', 'tech_gk_distribution'          , 'Distribution — short, long, under press'                             , 'توزيع الكرة'                                 ,  118),
    ('TECH', 'tech_gk_crosses'               , 'Cross claiming — command of area'                                    , 'التعامل مع العرضيات'                         ,  119),
    ('TECH', 'tech_gk_sweeper'               , 'Sweeping behind defensive line'                                      , 'اللعب كالليبيرو'                             ,  120),
    -- TACT
    ('TACT', 'tact_positioning_def'          , 'Defensive positioning'                                               , 'التموضع الدفاعي'                             ,  201),
    ('TACT', 'tact_positioning_att'          , 'Attacking positioning (off the ball)'                                , 'التموضع الهجومي'                             ,  202),
    ('TACT', 'tact_scanning'                 , 'Scanning frequency before receiving'                                 , 'النظر للمحيط قبل الاستلام'                   ,  203),
    ('TACT', 'tact_body_orientation'         , 'Body orientation when receiving'                                     , 'اتجاه الجسم عند الاستلام'                    ,  204),
    ('TACT', 'tact_decision_making'          , 'Decision-making speed & quality'                                     , 'اتخاذ القرار'                                ,  205),
    ('TACT', 'tact_off_ball_movement'        , 'Off-ball movement & space creation'                                  , 'الحركة بدون كرة'                             ,  206),
    ('TACT', 'tact_runs_in_behind'           , 'Runs in behind — timing & frequency'                                 , 'الجري خلف الدفاع'                            ,  207),
    ('TACT', 'tact_pressing_trigger'         , 'Pressing — recognition of triggers'                                  , 'قراءة لحظات الضغط'                           ,  208),
    ('TACT', 'tact_pressing_intensity'       , 'Pressing — intensity & sustainability'                               , 'شدة الضغط'                                   ,  209),
    ('TACT', 'tact_def_shape'                , 'Maintaining defensive shape (within unit)'                           , 'الانضباط الدفاعي'                            ,  210),
    ('TACT', 'tact_def_recovery'             , 'Recovery work after losing ball'                                     , 'العودة الدفاعية'                             ,  211),
    ('TACT', 'tact_marking'                  , 'Marking discipline (zonal & man-to-man)'                             , 'الرقابة'                                     ,  212),
    ('TACT', 'tact_back_post_cover'          , 'Back-post coverage on diagonal balls'                                , 'تغطية القائم البعيد'                         ,  213),
    ('TACT', 'tact_long_ball_cover'          , 'Covering depth on long balls / counter'                              , 'التغطية في الكرات الطويلة'                   ,  214),
    ('TACT', 'tact_one_v_one_def'            , '1v1 defending — body shape, timing'                                  , 'الدفاع الفردي'                               ,  215),
    ('TACT', 'tact_build_up'                 , 'Build-up contribution from back/middle third'                        , 'بناء الهجمة'                                 ,  216),
    ('TACT', 'tact_third_man_runs'           , 'Third-man runs / combination play'                                   , 'لعب المثلثات'                                ,  217),
    ('TACT', 'tact_communication'            , 'Tactical communication / organising teammates'                       , 'التواصل التكتيكي'                            ,  218),
    ('TACT', 'tact_transition_def_to_att'    , 'Defensive → attacking transition speed'                              , 'الانتقال من الدفاع للهجوم'                   ,  219),
    ('TACT', 'tact_transition_att_to_def'    , 'Attacking → defensive transition speed'                              , 'الانتقال من الهجوم للدفاع'                   ,  220),
    -- PHYS
    ('PHYS', 'phys_speed_acceleration'       , 'Acceleration over 5–10m'                                             , 'التسارع'                                     ,  301),
    ('PHYS', 'phys_speed_top'                , 'Top speed'                                                           , 'السرعة القصوى'                               ,  302),
    ('PHYS', 'phys_strength_duels'           , 'Strength in ground duels (50/50s, shoulder-to-shoulder)'             , 'القوة في الالتحامات'                         ,  303),
    ('PHYS', 'phys_strength_aerial'          , 'Aerial dominance (jump + power)'                                     , 'القوة في الضربات الهوائية'                   ,  304),
    ('PHYS', 'phys_agility'                  , 'Agility — change of direction'                                       , 'الرشاقة'                                     ,  305),
    ('PHYS', 'phys_stamina_90min'            , 'Stamina across 90+ minutes'                                          , 'اللياقة (90 دقيقة كاملة)'                    ,  306),
    ('PHYS', 'phys_recovery_speed'           , 'Recovery speed (chasing back)'                                       , 'سرعة العودة'                                 ,  307),
    ('PHYS', 'phys_balance'                  , 'Balance under contact'                                               , 'التوازن'                                     ,  308),
    ('PHYS', 'phys_robustness'               , 'Physical robustness (handles contact, doesn''t go down easy)'        , 'الصلابة البدنية'                             ,  309),
    -- MENT
    ('MENT', 'ment_composure'                , 'Composure under pressure'                                            , 'الهدوء تحت الضغط'                            ,  401),
    ('MENT', 'ment_leadership'               , 'Leadership — vocal & by example'                                     , 'القيادة'                                     ,  402),
    ('MENT', 'ment_concentration'            , 'Concentration over full match'                                       , 'التركيز'                                     ,  403),
    ('MENT', 'ment_resilience'               , 'Resilience after mistakes (visible in body language)'                , 'تحمل الأخطاء'                                ,  404),
    ('MENT', 'ment_work_rate'                , 'Work rate without the ball'                                          , 'الجهد بدون كرة'                              ,  405),
    ('MENT', 'ment_winning_mentality'        , 'Visible winning mentality / hunger / will to win duels'              , 'عقلية الفوز'                                 ,  406)
) AS v(cat_code, code, name_en, name_ar, sort_order)
JOIN criteria_categories cc ON cc.code = v.cat_code
ON CONFLICT (code) DO NOTHING;

-- Position-group → criteria mapping (which form items appear for which group)
INSERT INTO position_group_criteria (position_group_id, criterion_id, sort_order)
SELECT pg.id, c.id, c.sort_order
FROM criteria c
JOIN (VALUES
    -- TECH
    ('tech_first_touch'                , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('tech_passing_short'              , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('tech_passing_long'               , ARRAY['GK','CB','FB','DM','CM','AM']),
    ('tech_passing_press'              , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('tech_passing_progressive'        , ARRAY['DM','CM','AM','FB']),
    ('tech_crossing'                   , ARRAY['FB','W','AM']),
    ('tech_finishing'                  , ARRAY['DM','CM','AM','W','ST']),
    ('tech_finishing_chances'          , ARRAY['AM','W','ST']),
    ('tech_dribbling_1v1'              , ARRAY['FB','DM','CM','AM','W','ST']),
    ('tech_dribbling_press'            , ARRAY['CM','AM','W']),
    ('tech_set_pieces_taking'          , ARRAY['CB','FB','CM','AM']),
    ('tech_set_pieces_attacking'       , ARRAY['CB','AM','ST']),
    ('tech_heading_offensive'          , ARRAY['CB','AM','ST']),
    ('tech_heading_defensive'          , ARRAY['GK','CB','FB','DM']),
    ('tech_ball_striking'              , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tech_gk_shot_stopping'           , ARRAY['GK']),
    ('tech_gk_handling'                , ARRAY['GK']),
    ('tech_gk_distribution'            , ARRAY['GK']),
    ('tech_gk_crosses'                 , ARRAY['GK']),
    ('tech_gk_sweeper'                 , ARRAY['GK']),
    -- TACT
    ('tact_positioning_def'            , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('tact_positioning_att'            , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_scanning'                   , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('tact_body_orientation'           , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_decision_making'            , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('tact_off_ball_movement'          , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_runs_in_behind'             , ARRAY['AM','W','ST']),
    ('tact_pressing_trigger'           , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_pressing_intensity'         , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_def_shape'                  , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_def_recovery'               , ARRAY['FB','CM','AM','W']),
    ('tact_marking'                    , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_back_post_cover'            , ARRAY['CB','FB','DM']),
    ('tact_long_ball_cover'            , ARRAY['CB','FB','DM']),
    ('tact_one_v_one_def'              , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_build_up'                   , ARRAY['GK','CB','FB','DM']),
    ('tact_third_man_runs'             , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_communication'              , ARRAY['GK','CB','DM','CM']),
    ('tact_transition_def_to_att'      , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('tact_transition_att_to_def'      , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    -- PHYS
    ('phys_speed_acceleration'         , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('phys_speed_top'                  , ARRAY['CB','FB','AM','W','ST']),
    ('phys_strength_duels'             , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('phys_strength_aerial'            , ARRAY['GK','CB','ST']),
    ('phys_agility'                    , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('phys_stamina_90min'              , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('phys_recovery_speed'             , ARRAY['CB','FB','DM','W']),
    ('phys_balance'                    , ARRAY['CB','FB','DM','CM','AM','W','ST']),
    ('phys_robustness'                 , ARRAY['CB','FB','DM','ST']),
    -- MENT
    ('ment_composure'                  , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('ment_leadership'                 , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('ment_concentration'              , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('ment_resilience'                 , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('ment_work_rate'                  , ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('ment_winning_mentality'          , ARRAY['GK','CB','FB','DM','CM','AM','W','ST'])
) AS m(criterion_code, group_codes) ON c.code = m.criterion_code
JOIN position_groups pg ON pg.code = ANY(m.group_codes)
ON CONFLICT (position_group_id, criterion_id) DO NOTHING;

-- =============================================================
-- VERIFICATION VIEWS (optional, useful in dev)
-- =============================================================
CREATE OR REPLACE VIEW v_position_group_form_counts AS
SELECT pg.code AS position_group,
       COUNT(pgc.criterion_id) AS criteria_count
FROM position_groups pg
LEFT JOIN position_group_criteria pgc ON pgc.position_group_id = pg.id
GROUP BY pg.code, pg.sort_order
ORDER BY pg.sort_order;

-- Run after seeding to verify each group has a sensible form size:
-- SELECT * FROM v_position_group_form_counts;
-- Expected (Phase 5a v2-LOCKED): GK 24, CB 42, FB 42, DM 40, CM 37, AM 42, W 38, ST 38.

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
                    CHECK (role IN ('admin','technical_director','scout','viewer')),
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
    is_active              BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by             INTEGER REFERENCES users(id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_players_name        ON players(full_name);
CREATE INDEX IF NOT EXISTS idx_players_position    ON players(primary_position_id);
CREATE INDEX IF NOT EXISTS idx_players_national_id ON players(national_id);
CREATE INDEX IF NOT EXISTS idx_players_active      ON players(is_active);


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
    match_label         VARCHAR(255),
    match_date          DATE,
    competition         VARCHAR(128),
    minutes_observed    INTEGER,

    overall_rating      NUMERIC(4,2),
    summary             TEXT,
    recommendation      VARCHAR(32)
                        CHECK (recommendation IN
                            ('monitor','call_up','shortlist','release','not_ready')
                            OR recommendation IS NULL),
    status              VARCHAR(16) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','submitted','locked')),

    submitted_at        TIMESTAMPTZ,
    locked_at           TIMESTAMPTZ,
    locked_by           INTEGER REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_player     ON evaluations(player_id);
CREATE INDEX IF NOT EXISTS idx_eval_evaluator  ON evaluations(evaluator_id);
CREATE INDEX IF NOT EXISTS idx_eval_status     ON evaluations(status);
CREATE INDEX IF NOT EXISTS idx_eval_match_date ON evaluations(match_date);

CREATE TABLE IF NOT EXISTS evaluation_scores (
    id            SERIAL PRIMARY KEY,
    evaluation_id INTEGER      NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    criterion_id  INTEGER      NOT NULL REFERENCES criteria(id)   ON DELETE RESTRICT,
    score         NUMERIC(4,2) NOT NULL,
    comment       TEXT,
    UNIQUE (evaluation_id, criterion_id)
);
CREATE INDEX IF NOT EXISTS idx_eval_scores_eval      ON evaluation_scores(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_eval_scores_criterion ON evaluation_scores(criterion_id);


-- =============================================================
-- 6. WYSCOUT INTEGRATION
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

    -- match identity (parsed from the "Match" column)
    match_label                 VARCHAR(255) NOT NULL,
    competition                 VARCHAR(128),
    match_date                  DATE NOT NULL,
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


-- =============================================================
-- 7. AI ARTIFACTS (Gemini outputs cached for re-use)
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
-- SEED DATA
-- =============================================================

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

-- Starter criteria seed (~35) — admins extend via UI
-- Format: (category_code, criterion_code, name_en, name_ar)
INSERT INTO criteria (category_id, code, name_en, name_ar, sort_order)
SELECT cc.id, v.code, v.name_en, v.name_ar, v.sort_order
FROM (VALUES
    -- TECHNICAL
    ('TECH', 'first_touch',         'First touch',                     'استلام الكرة',          10),
    ('TECH', 'short_passing',       'Short passing accuracy',          'دقة التمرير القصير',   20),
    ('TECH', 'long_passing',        'Long passing range & accuracy',   'دقة ومدى التمرير',     30),
    ('TECH', 'crossing',            'Crossing',                        'العرضيات',              40),
    ('TECH', 'dribbling_1v1',       'Dribbling 1v1',                   'المراوغة الفردية',     50),
    ('TECH', 'finishing',           'Finishing',                       'التهديف',               60),
    ('TECH', 'heading_offensive',   'Heading (offensive)',             'الضربات الرأسية الهجومية', 70),
    ('TECH', 'heading_defensive',   'Heading (defensive)',             'الضربات الرأسية الدفاعية', 80),
    ('TECH', 'long_shots',          'Shooting from distance',          'التسديد من بعيد',      90),
    ('TECH', 'set_pieces',          'Set pieces',                      'الكرات الثابتة',       100),
    ('TECH', 'control_under_press', 'Ball control under pressure',     'التحكم تحت الضغط',     110),
    ('TECH', 'gk_distribution',     'Distribution / kicking (GK)',     'توزيع الكرة (حارس)',   120),
    ('TECH', 'gk_shot_stopping',    'Shot stopping (GK)',              'التصدي (حارس)',        130),
    ('TECH', 'gk_handling',         'Handling / catching (GK)',        'الاستحواذ والإمساك',   140),
    -- TACTICAL
    ('TACT', 'positioning',         'Positional awareness',            'الوعي التكتيكي',       210),
    ('TACT', 'reading_game',        'Reading the game',                'قراءة المباراة',       220),
    ('TACT', 'off_ball_movement',   'Off-ball movement',               'التحرك بدون كرة',      230),
    ('TACT', 'pressing',            'Pressing intensity & timing',     'الضغط وتوقيته',        240),
    ('TACT', 'def_shape',           'Defensive shape',                 'الانضباط الدفاعي',     250),
    ('TACT', 'one_v_one_def',       '1v1 defending',                   'الدفاع الفردي',        260),
    ('TACT', 'marking',             'Marking discipline',              'الرقابة',              270),
    ('TACT', 'build_up',            'Build-up contribution',           'بناء الهجمة',          280),
    ('TACT', 'creating_space',      'Creating space',                  'صناعة المساحات',      290),
    ('TACT', 'transition_speed',    'Transition speed',                'سرعة الانتقال',        300),
    ('TACT', 'decision_making',     'Decision-making',                 'اتخاذ القرار',         310),
    ('TACT', 'communication',       'Communication / organising',      'التواصل والتنظيم',    320),
    -- PHYSICAL
    ('PHYS', 'pace',                'Pace / acceleration',             'السرعة',                410),
    ('PHYS', 'stamina',             'Stamina / endurance',             'اللياقة',               420),
    ('PHYS', 'strength',            'Strength / duels',                'القوة البدنية',        430),
    ('PHYS', 'aerial',              'Aerial dominance',                'القوة الهوائية',       440),
    ('PHYS', 'agility',             'Agility',                         'الرشاقة',               450),
    ('PHYS', 'recovery_speed',      'Recovery speed',                  'سرعة العودة',          460),
    -- MENTAL
    ('MENT', 'composure',           'Composure under pressure',        'الهدوء تحت الضغط',     510),
    ('MENT', 'leadership',          'Leadership',                      'القيادة',               520),
    ('MENT', 'concentration',       'Concentration',                   'التركيز',               530),
    ('MENT', 'resilience',          'Resilience after mistakes',       'تحمل الأخطاء',         540),
    ('MENT', 'desire',              'Aggression / desire',             'الرغبة والشغف',        550),
    ('MENT', 'discipline',          'Discipline',                      'الانضباط',              560),
    ('MENT', 'coachability',        'Coachability',                    'تقبل التوجيه',         570)
) AS v(cat_code, code, name_en, name_ar, sort_order)
JOIN criteria_categories cc ON cc.code = v.cat_code
ON CONFLICT (code) DO NOTHING;

-- Position-group → criteria mapping (which form items appear for which group)
-- Pattern: criterion applies to listed groups
INSERT INTO position_group_criteria (position_group_id, criterion_id, sort_order)
SELECT pg.id, c.id, c.sort_order
FROM criteria c
JOIN (VALUES
    -- TECHNICAL
    ('first_touch',         ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('short_passing',       ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('long_passing',        ARRAY['GK','CB','FB','DM','CM','AM']),
    ('crossing',            ARRAY['FB','W','AM']),
    ('dribbling_1v1',       ARRAY['FB','CM','AM','W','ST']),
    ('finishing',           ARRAY['AM','W','ST']),
    ('heading_offensive',   ARRAY['CB','AM','ST']),
    ('heading_defensive',   ARRAY['CB','FB','DM','ST']),
    ('long_shots',          ARRAY['CM','AM','ST']),
    ('set_pieces',          ARRAY['CB','FB','CM','AM']),
    ('control_under_press', ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('gk_distribution',     ARRAY['GK']),
    ('gk_shot_stopping',    ARRAY['GK']),
    ('gk_handling',         ARRAY['GK']),
    -- TACTICAL
    ('positioning',         ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('reading_game',        ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('off_ball_movement',   ARRAY['FB','CM','AM','W','ST']),
    ('pressing',            ARRAY['FB','DM','CM','AM','W','ST']),
    ('def_shape',           ARRAY['CB','FB','DM','CM']),
    ('one_v_one_def',       ARRAY['CB','FB','DM']),
    ('marking',             ARRAY['CB','FB','DM']),
    ('build_up',            ARRAY['GK','CB','FB','DM']),
    ('creating_space',      ARRAY['AM','W','ST']),
    ('transition_speed',    ARRAY['FB','CM','AM','W','ST']),
    ('decision_making',     ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('communication',       ARRAY['GK','CB','DM']),
    -- PHYSICAL
    ('pace',                ARRAY['CB','FB','W','ST']),
    ('stamina',             ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('strength',            ARRAY['CB','FB','DM','ST']),
    ('aerial',              ARRAY['GK','CB','ST']),
    ('agility',             ARRAY['GK','FB','AM','W']),
    ('recovery_speed',      ARRAY['CB','FB','DM']),
    -- MENTAL (all groups)
    ('composure',           ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('leadership',          ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('concentration',       ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('resilience',          ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('desire',              ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('discipline',          ARRAY['GK','CB','FB','DM','CM','AM','W','ST']),
    ('coachability',        ARRAY['GK','CB','FB','DM','CM','AM','W','ST'])
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
-- Expected: each group ~18-25 criteria, GK distinct from outfield groups.

-- Design specification, not an applied migration. Validate in an empty PostgreSQL database.
BEGIN;
CREATE TABLE branches (
    id uuid PRIMARY KEY, postal_code text NOT NULL, name text NOT NULL,
    address text NOT NULL, timezone text NOT NULL, active boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX uq_branches_postal_code ON branches(postal_code);
CREATE TABLE branch_working_hours (
    branch_id uuid NOT NULL REFERENCES branches(id),
    weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    opens_at time, closes_at time, is_closed boolean NOT NULL DEFAULT false,
    PRIMARY KEY (branch_id, weekday),
    CHECK (
        (is_closed AND opens_at IS NULL AND closes_at IS NULL)
        OR (NOT is_closed AND opens_at IS NOT NULL AND closes_at IS NOT NULL AND closes_at > opens_at)
    )
);
CREATE TABLE services (
    id uuid PRIMARY KEY, name text NOT NULL, active boolean NOT NULL DEFAULT true
);
CREATE TABLE branch_services (
    branch_id uuid NOT NULL REFERENCES branches(id), service_id uuid NOT NULL REFERENCES services(id),
    active boolean NOT NULL DEFAULT true,
    average_service_seconds integer NOT NULL CHECK (average_service_seconds > 0),
    PRIMARY KEY (branch_id, service_id)
);
CREATE TABLE staff_members (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL REFERENCES branches(id),
    employee_code text NOT NULL, display_name text NOT NULL,
    role text NOT NULL CHECK (role IN ('operator', 'manager')),
    pin_salt bytea NOT NULL, pin_hash bytea NOT NULL, active boolean NOT NULL DEFAULT true,
    failed_login_count integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until timestamptz, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE (branch_id, id)
);
CREATE UNIQUE INDEX staff_members_branch_code ON staff_members(branch_id, lower(employee_code));
CREATE INDEX staff_members_active_branch ON staff_members(branch_id, role) WHERE active;
CREATE TABLE staff_sessions (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL REFERENCES branches(id),
    staff_member_id uuid,
    employee_code text NOT NULL, role text NOT NULL CHECK (role IN ('operator', 'manager')),
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), expires_at timestamptz NOT NULL,
    revoked_at timestamptz, CHECK (expires_at > created_at),
    FOREIGN KEY (branch_id, staff_member_id) REFERENCES staff_members(branch_id, id)
);
CREATE INDEX staff_sessions_branch ON staff_sessions(branch_id, expires_at);
CREATE INDEX staff_sessions_member_active ON staff_sessions(staff_member_id, expires_at) WHERE revoked_at IS NULL;
CREATE TABLE windows (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL REFERENCES branches(id),
    number integer NOT NULL CHECK (number > 0),
    status text NOT NULL DEFAULT 'closed' CHECK (status IN ('closed', 'open', 'draining')),
    operator_session_id uuid UNIQUE REFERENCES staff_sessions(id),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    CONSTRAINT window_operator_required CHECK ((status = 'closed') = (operator_session_id IS NULL)),
    UNIQUE (branch_id, id), UNIQUE (branch_id, number)
);
CREATE TABLE window_services (
    branch_id uuid NOT NULL, window_id uuid NOT NULL, service_id uuid NOT NULL,
    PRIMARY KEY (branch_id, window_id, service_id),
    FOREIGN KEY (branch_id, window_id) REFERENCES windows(branch_id, id),
    FOREIGN KEY (branch_id, service_id) REFERENCES branch_services(branch_id, service_id)
);
CREATE TABLE window_events (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL, window_id uuid NOT NULL,
    window_version bigint NOT NULL CHECK (window_version > 0), actor_id text NOT NULL,
    action text NOT NULL, before_state jsonb, after_state jsonb NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (branch_id, window_id) REFERENCES windows(branch_id, id),
    UNIQUE (window_id, window_version)
);
CREATE TABLE appointment_slots (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL, service_id uuid NOT NULL,
    starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL,
    capacity integer NOT NULL CHECK (capacity > 0),
    reserved integer NOT NULL DEFAULT 0 CHECK (reserved >= 0 AND reserved <= capacity),
    active boolean NOT NULL DEFAULT true, CHECK (ends_at > starts_at),
    FOREIGN KEY (branch_id, service_id) REFERENCES branch_services(branch_id, service_id),
    UNIQUE (branch_id, service_id, id), UNIQUE (branch_id, service_id, starts_at)
);
CREATE TABLE client_sessions (
    id uuid PRIMARY KEY, token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), expires_at timestamptz NOT NULL,
    CHECK (expires_at > created_at)
);
CREATE TABLE priority_rules (
    branch_id uuid NOT NULL REFERENCES branches(id), version bigint NOT NULL CHECK (version > 0),
    config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'), active boolean NOT NULL DEFAULT true,
    actor_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (branch_id, version)
);
CREATE UNIQUE INDEX one_active_rule ON priority_rules(branch_id) WHERE active;
CREATE TABLE tickets (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL REFERENCES branches(id), service_id uuid NOT NULL,
    ticket_number bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    queue_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    source text NOT NULL CHECK (source IN ('prebooking', 'qr', 'walk_in')),
    status text NOT NULL CHECK (status IN ('booked', 'waiting', 'called', 'serving', 'served', 'no_show', 'cancelled')),
    window_id uuid, target_window_id uuid, slot_id uuid,
    session_id uuid REFERENCES client_sessions(id), scheduled_time timestamptz, eligible_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    called_at timestamptz, service_started_at timestamptz, closed_at timestamptz,
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    return_count integer NOT NULL DEFAULT 0 CHECK (return_count >= 0),
    redirect_count integer NOT NULL DEFAULT 0 CHECK (redirect_count >= 0),
    UNIQUE (branch_id, id),
    FOREIGN KEY (branch_id, service_id) REFERENCES branch_services(branch_id, service_id),
    FOREIGN KEY (branch_id, window_id, service_id) REFERENCES window_services(branch_id, window_id, service_id),
    FOREIGN KEY (branch_id, target_window_id, service_id) REFERENCES window_services(branch_id, window_id, service_id),
    FOREIGN KEY (branch_id, service_id, slot_id) REFERENCES appointment_slots(branch_id, service_id, id),
    CHECK ((source = 'prebooking') = (scheduled_time IS NOT NULL)),
    CHECK (source = 'prebooking' OR slot_id IS NULL),
    CHECK (source = 'walk_in' OR session_id IS NOT NULL),
    CHECK (status <> 'booked' OR (source = 'prebooking' AND slot_id IS NOT NULL)),
    CHECK ((status IN ('called', 'serving')) = (window_id IS NOT NULL)),
    CHECK (target_window_id IS NULL OR status = 'waiting'),
    CHECK ((status IN ('served', 'no_show', 'cancelled')) = (closed_at IS NOT NULL)),
    CHECK (status NOT IN ('called', 'serving') OR called_at IS NOT NULL),
    CHECK (status <> 'serving' OR service_started_at IS NOT NULL),
    CHECK (closed_at IS NULL OR closed_at >= created_at)
);
CREATE UNIQUE INDEX one_active_ticket_per_window ON tickets(branch_id, window_id) WHERE status IN ('called', 'serving');
CREATE INDEX waiting_candidates ON tickets(branch_id, service_id, queue_sequence) WHERE status = 'waiting';
CREATE INDEX booking_activation ON tickets(branch_id, eligible_at) WHERE status = 'booked';
CREATE INDEX session_tickets ON tickets(session_id, created_at);
CREATE TABLE ticket_events (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL, ticket_id uuid NOT NULL,
    ticket_version bigint NOT NULL CHECK (ticket_version > 0), action text NOT NULL,
    actor_id text NOT NULL, actor_role text NOT NULL, old_status text, new_status text NOT NULL,
    before_state jsonb, after_state jsonb NOT NULL, reason text, rule_version bigint,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (branch_id, ticket_id) REFERENCES tickets(branch_id, id),
    FOREIGN KEY (branch_id, rule_version) REFERENCES priority_rules(branch_id, version),
    UNIQUE (ticket_id, ticket_version), UNIQUE (branch_id, id)
);
CREATE INDEX ticket_events_time ON ticket_events(branch_id, occurred_at);
CREATE TABLE notification_log (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL, event_id uuid NOT NULL,
    channel text NOT NULL, payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'retry', 'sent', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(), locked_until timestamptz,
    last_error text, delivered_at timestamptz,
    FOREIGN KEY (branch_id, event_id) REFERENCES ticket_events(branch_id, id),
    UNIQUE (event_id, channel),
    CHECK ((status = 'processing') = (locked_until IS NOT NULL)),
    CHECK ((status = 'sent') = (delivered_at IS NOT NULL))
);
CREATE INDEX delivery_pending ON notification_log(next_attempt_at) WHERE status IN ('pending', 'retry');
CREATE INDEX delivery_expired ON notification_log(locked_until) WHERE status = 'processing';
CREATE TABLE incidents (
    id uuid PRIMARY KEY, branch_id uuid NOT NULL REFERENCES branches(id), window_id uuid, ticket_id uuid,
    actor_id text NOT NULL, category text NOT NULL CHECK (category IN ('technical', 'operational')),
    description text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), resolved_at timestamptz,
    FOREIGN KEY (branch_id, window_id) REFERENCES windows(branch_id, id),
    FOREIGN KEY (branch_id, ticket_id) REFERENCES tickets(branch_id, id)
);
CREATE TABLE idempotency_requests (
    branch_id uuid NOT NULL REFERENCES branches(id), actor_scope text NOT NULL, command text NOT NULL,
    key uuid NOT NULL, request_hash text NOT NULL,
    response_status integer NOT NULL CHECK (response_status BETWEEN 200 AND 599), response_body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (branch_id, actor_scope, command, key)
);
COMMIT;

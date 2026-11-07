ALTER TABLE customer_intake_invites ADD COLUMN email_notifications INTEGER NOT NULL DEFAULT 1 CHECK (email_notifications IN (0,1));
ALTER TABLE customer_case_contacts ADD COLUMN email_notifications INTEGER NOT NULL DEFAULT 1 CHECK (email_notifications IN (0,1));

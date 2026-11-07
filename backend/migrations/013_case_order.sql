-- Record the original SQLite insertion order so it also survives a Postgres import.
ALTER TABLE cases ADD COLUMN case_sequence INTEGER;
UPDATE cases SET case_sequence=rowid;
CREATE UNIQUE INDEX cases_sequence_idx ON cases(case_sequence);
CREATE TRIGGER cases_assign_sequence AFTER INSERT ON cases
WHEN NEW.case_sequence IS NULL
BEGIN
    UPDATE cases SET case_sequence=NEW.rowid WHERE id=NEW.id;
END;

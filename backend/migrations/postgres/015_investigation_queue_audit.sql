CREATE FUNCTION investigate_jobs_enqueue_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF TG_OP='INSERT' OR NEW.revision<>OLD.revision THEN
INSERT INTO investigation_audit VALUES(gen_random_uuid()::text,NEW.resolution_id,NEW.merchant_id,to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'),'investigation_enqueued',json_build_object('revision',NEW.revision)::text);
END IF;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_jobs_enqueue AFTER INSERT OR UPDATE ON investigation_jobs FOR EACH ROW EXECUTE FUNCTION investigate_jobs_enqueue_fn();
INSERT INTO investigation_audit SELECT gen_random_uuid()::text,resolution_id,merchant_id,to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'),'investigation_enqueued',json_build_object('revision',revision)::text FROM investigation_jobs WHERE state='queued';

CREATE TRIGGER investigate_jobs_enqueue_insert AFTER INSERT ON investigation_jobs BEGIN
INSERT INTO investigation_audit VALUES(lower(hex(randomblob(16))),NEW.resolution_id,NEW.merchant_id,strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),'investigation_enqueued',json_object('revision',NEW.revision));
END;
CREATE TRIGGER investigate_jobs_enqueue_update AFTER UPDATE ON investigation_jobs WHEN NEW.revision<>OLD.revision BEGIN
INSERT INTO investigation_audit VALUES(lower(hex(randomblob(16))),NEW.resolution_id,NEW.merchant_id,strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),'investigation_enqueued',json_object('revision',NEW.revision));
END;
INSERT INTO investigation_audit SELECT lower(hex(randomblob(16))),resolution_id,merchant_id,strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),'investigation_enqueued',json_object('revision',revision) FROM investigation_jobs WHERE state='queued';

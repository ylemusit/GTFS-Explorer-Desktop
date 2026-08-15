ALTER TABLE import_jobs ADD COLUMN phase VARCHAR;
UPDATE import_jobs SET phase = 'PENDING' WHERE phase IS NULL;

-- EKAIA Puerto - Database Initialization

USE ekaia_puerto;

-- Create indexes for performance
CREATE INDEX idx_vehicle_records_plate ON vehicle_records(plate);
CREATE INDEX idx_vehicle_records_status ON vehicle_records(status);
CREATE INDEX idx_vehicle_records_entry_time ON vehicle_records(entry_time);
CREATE INDEX idx_detection_logs_camera ON detection_logs(camera);
CREATE INDEX idx_detection_logs_timestamp ON detection_logs(timestamp);

-- Insert sample data (optional, for testing)
-- INSERT INTO vehicle_records (plate, entry_time, status) VALUES ('ABCD12', NOW(), 'inside');

resource "aws_db_subnet_group" "production" {
  name        = "task-manager-db-subnet-group"
  description = "Subnets for the task manager PostgreSQL database"

  subnet_ids = [
    data.aws_subnet.default_1a.id,
    data.aws_subnet.default_1b.id,
    data.aws_subnet.default_1c.id,
  ]

  tags = {
    Name = "task-manager-prod-db-subnet-group"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_db_instance" "production" {
  identifier = "task-manager-db"

  engine         = "postgres"
  engine_version = "17.10"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_master_username
  port     = 5432

  availability_zone   = "il-central-1b"
  multi_az            = false
  publicly_accessible = false

  db_subnet_group_name = aws_db_subnet_group.production.name

  vpc_security_group_ids = [
    aws_security_group.rds.id
  ]

  parameter_group_name = "default.postgres17"

  backup_retention_period = 1
  backup_window           = "05:50-06:20"
  maintenance_window      = "tue:06:51-tue:07:21"

  auto_minor_version_upgrade = true
  apply_immediately          = false

  deletion_protection   = true
  skip_final_snapshot   = true
  copy_tags_to_snapshot = true

  performance_insights_enabled = true
  monitoring_interval          = 0

  tags = {
    Name = "task-manager-prod-db"
  }

  lifecycle {
    prevent_destroy = true
  }
}

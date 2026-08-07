resource "aws_security_group" "ec2" {
  name        = "task-manager-sg"
  description = "task-manager-sg created 2026-07-28T16:19:09.627Z"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "task-manager-prod-ec2-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ec2_http" {
  security_group_id = aws_security_group.ec2.id

  description = "Allow public HTTP traffic"
  ip_protocol = "tcp"
  from_port   = 80
  to_port     = 80
  cidr_ipv4   = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "ec2_https" {
  security_group_id = aws_security_group.ec2.id

  description = "Allow public HTTPS traffic"
  ip_protocol = "tcp"
  from_port   = 443
  to_port     = 443
  cidr_ipv4   = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "ec2_ssh" {
  security_group_id = aws_security_group.ec2.id

  description = "Allow SSH from the administrator IP"
  ip_protocol = "tcp"
  from_port   = 22
  to_port     = 22
  cidr_ipv4   = var.ssh_allowed_cidr
}

resource "aws_vpc_security_group_egress_rule" "ec2_all_outbound" {
  security_group_id = aws_security_group.ec2.id

  description = "Allow all outbound traffic"
  ip_protocol = "-1"
  cidr_ipv4   = "0.0.0.0/0"
}

resource "aws_security_group" "rds" {
  name        = "task-manager-rds-sg"
  description = "Allow PostgreSQL access from the task manager EC2 instance"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "task-manager-prod-rds-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "rds_postgresql_from_ec2" {
  security_group_id = aws_security_group.rds.id

  description                  = "Allow PostgreSQL from the task manager EC2 security group"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.ec2.id
}

resource "aws_vpc_security_group_egress_rule" "rds_all_outbound" {
  security_group_id = aws_security_group.rds.id

  description = "Allow all outbound traffic"
  ip_protocol = "-1"
  cidr_ipv4   = "0.0.0.0/0"
}

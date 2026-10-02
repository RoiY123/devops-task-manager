resource "aws_instance" "app_previous" {
  ami                  = "ami-0d3dfbd3aedad5847"
  instance_type        = "t3.micro"
  key_name             = "task-manager-key"
  subnet_id            = data.aws_subnet.default_1b.id
  iam_instance_profile = aws_iam_instance_profile.app.name

  vpc_security_group_ids = [
    aws_security_group.ec2.id
  ]

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  monitoring                  = false
  source_dest_check           = true
  disable_api_termination     = true
  ebs_optimized               = true
  user_data_replace_on_change = false

  root_block_device {
    volume_size           = 10
    volume_type           = "gp3"
    encrypted             = false
    delete_on_termination = true
  }

  tags = {
    Name = "task-manager-prod-api-rollback"
  }

  lifecycle {
    prevent_destroy = true
  }
}

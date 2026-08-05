resource "aws_instance" "app" {
  ami           = "ami-0d3dfbd3aedad5847"
  instance_type = "t3.micro"
  key_name      = "task-manager-key"
  subnet_id     = "subnet-03e021df4a8b0a285"

  vpc_security_group_ids = [
    aws_security_group.ec2.id
  ]

  monitoring                  = false
  source_dest_check           = true
  disable_api_termination     = false
  ebs_optimized               = true
  user_data_replace_on_change = false

  root_block_device {
    volume_size           = 10
    volume_type           = "gp3"
    encrypted             = false
    delete_on_termination = true
  }

  tags = {
    Name = "task-manager-prod-api"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_eip" "app" {
  domain = "vpc"

  tags = {
    Name = "task-manager-prod-eip"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_eip_association" "app" {
  allocation_id = aws_eip.app.id
  instance_id   = aws_instance.app.id
}

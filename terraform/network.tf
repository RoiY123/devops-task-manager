data "aws_vpc" "default" {
  default = true
}

data "aws_subnet" "default_1a" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "il-central-1a"
  default_for_az    = true
}

data "aws_subnet" "default_1b" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "il-central-1b"
  default_for_az    = true
}

data "aws_subnet" "default_1c" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "il-central-1c"
  default_for_az    = true
}

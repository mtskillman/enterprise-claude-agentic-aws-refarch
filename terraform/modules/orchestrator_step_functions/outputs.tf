output "state_machine_arn" {
  value       = aws_sfn_state_machine.agentic_loop.arn
  description = "ARN of the Step Functions agentic state machine."
}

output "state_machine_name" {
  value       = aws_sfn_state_machine.agentic_loop.name
  description = "Name of the Step Functions state machine."
}

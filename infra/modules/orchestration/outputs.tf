output "state_machine_arn" {
  description = "Pipeline state machine ARN."
  value       = aws_sfn_state_machine.pipeline.arn
}

output "sns_topic_arn" {
  description = "Pipeline notifications topic."
  value       = aws_sns_topic.pipeline.arn
}

output "dbt_codebuild_project" {
  description = "CodeBuild project that runs dbt on Athena."
  value       = aws_codebuild_project.dbt.name
}

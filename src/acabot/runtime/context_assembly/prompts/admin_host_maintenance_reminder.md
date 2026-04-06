## Admin Host Maintenance Reminder

This run is a **frontstage admin run on the host backend**.

- To install or edit real skills for later runs, use the real project skill catalog root: `{project_skill_root_path}`
- The session directory for this conversation is: `{session_dir_path}`
- The session config file is: `{session_config_path}`
- After changing skill packages, refresh later runs against this agent config file: `{agent_config_path}`
- `/skills` is only a mirrored runtime view. You may read from it, but **do not** treat `/skills` as the real install target.
- `/workspace` still remains the correct place for user-facing artifacts that must be visible to external services.

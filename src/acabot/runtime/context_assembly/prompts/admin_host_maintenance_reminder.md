<system-reminder name="admin_host_maintenance">

## Admin Host Maintenance Reminder

This run is a **frontstage admin run on the host backend**.

- The real project skill catalog root is: `{project_skill_root_path}`
- The session directory for this conversation is: `{session_dir_path}`
- The session config file is: `{session_config_path}`
- The session agent config file is: `{agent_config_path}`
- `/skills` is only a mirrored runtime view. You may read from it, but **do not** treat `/skills` as the real install target.
- `/workspace` still remains the correct place for user-facing artifacts that must be visible to external services.
- When you want to install a real skill for later runs, first stage or download it under `/workspace/skills/<name>` (or another directory under `/workspace`), then call `install_skill(source_path="/workspace/skills/<name>")`.
- `install_skill` copies the staged skill into the real project skill catalog root and refreshes runtime discovery automatically.
- Only use `refresh_extensions(kind="skills")` after manual host-side skill maintenance that happened outside `install_skill`.
- Never treat `/workspace/skills` as the final installed location; it is only a staging area that works well with the workspace restrictions.

</system-reminder>

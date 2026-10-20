use super::*;

#[test]
fn combined_global_options_leave_command_flags_and_shell_arguments_intact() {
    for globals in [
        vec!["-Ltest-a", "-f/dev/null", "-CC"],
        vec!["-L", "test-a", "-f", "/dev/null", "-C", "-C"],
    ] {
        let mut arguments = vec!["tmuxx"];
        arguments.extend(globals);
        let command = [
            "new-session",
            "-d",
            "-x",
            "1",
            "sh",
            "-c",
            "printf %s \"$1\"",
            "--",
            "-f",
            ";",
            "list-sessions",
        ];
        arguments.extend(command);
        let cli = Cli::try_parse_from(arguments).unwrap();
        assert_eq!(cli.label.as_deref(), Some("test-a"));
        assert_eq!(cli.config, [PathBuf::from("/dev/null")]);
        assert_eq!(cli.control, 2);
        assert_eq!(cli.command, command.map(OsString::from));
    }
}

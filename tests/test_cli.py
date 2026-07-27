from repopilot.cli import main


def test_reviewforge_cli_message(capsys) -> None:
    main()
    assert "ReviewForge" in capsys.readouterr().out


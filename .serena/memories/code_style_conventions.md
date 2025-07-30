# Code Style and Conventions

## Python Code Style
- **Encoding**: UTF-8 for all files and string operations
- **International Support**: Handle German umlauts (ä, ö, ü) and Unicode characters
- **Version Format**: X.Y.Z in script headers
- **Date Format**: DD.MM.YYYY (German format, e.g., 24.06.2025)
- **Shebang**: `#!/usr/bin/python3` for all Python scripts

## Documentation Language
- **Code Comments**: Always in English
- **User Communication**: German (responses start with "Aye, Aye Captain")
- **Technical Documentation**: English for code, German for user-facing content

## Git Commit Conventions
- **[ADD]**: New features or extensions
- **[CHG]**: Modifications or changes in existing code
- **[FIX]**: Bug fixes

## Version Management Rules
- **Always increment version** when modifying scripts with version headers
- **Update date** to current date (check environment information)
- **NEVER use hardcoded old dates** - verify current date from environment

## File Organization
- Scripts in `/scripts/` directory
- Configuration files in `/config/` (YAML format preferred)
- Dockerfiles in `/Dockerfiles/` with version subdirectories
- Documentation files: README.md, CLAUDE.md

## Error Handling
- Comprehensive logging with proper error messages
- Graceful degradation for missing dependencies
- Version checking before installations/updates
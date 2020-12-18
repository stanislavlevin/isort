""""""
from pathlib import Path
from typing import Iterator, NamedTuple, Optional, TextIO

from isort.parse import _normalize_line, _strip_syntax, skip_line

from .comments import parse as parse_comments
from .settings import DEFAULT_CONFIG, Config


def import_type(line: str, config: Config = DEFAULT_CONFIG) -> Optional[str]:
    """If the current line is an import line it will return its type (from or straight)"""
    if line.lstrip().startswith(("import ", "cimport ")):
        return "straight"
    if line.lstrip().startswith("from "):
        return "from"
    return None


class IdentifiedImport(NamedTuple):
    line_number: int
    indented: bool
    module: str
    attribute: Optional[str] = None
    alias: Optional[str] = None
    src: Optional[Path] = None
    cimport: bool = False


def imports(input_stream: TextIO, config: Config = DEFAULT_CONFIG) -> Iterator[IdentifiedImport]:
    """Parses a python file taking out and categorizing imports."""
    in_quote = ""

    indexed_input = enumerate(input_stream)
    for index, line in indexed_input:
        (skipping_line, in_quote) = skip_line(
            line, in_quote=in_quote, index=index, section_comments=config.section_comments
        )

        if skipping_line:
            continue

        line, *end_of_line_comment = line.split("#", 1)
        indented = line.startswith(" ") or line.startswith("\n")
        statements = [line.strip() for line in line.split(";")]
        if end_of_line_comment:
            statements[-1] = f"{statements[-1]}#{end_of_line_comment[0]}"

        for statement in statements:
            line, raw_line = _normalize_line(statement)
            type_of_import = import_type(line, config) or ""
            if not type_of_import:
                continue

            import_string, _ = parse_comments(line)
            normalized_import_string = (
                import_string.replace("import(", "import (").replace("\\", " ").replace("\n", " ")
            )
            cimports: bool = (
                " cimport " in normalized_import_string
                or normalized_import_string.startswith("cimport")
            )

            if "(" in line.split("#", 1)[0]:
                while not line.split("#")[0].strip().endswith(")"):
                    try:
                        index, next_line = next(indexed_input)
                    except StopIteration:
                        break

                    line, _ = parse_comments(next_line)
                    import_string += "\n" + line
            else:
                while line.strip().endswith("\\"):
                    index, next_line = next(indexed_input)
                    line, _ = parse_comments(next_line)

                    # Still need to check for parentheses after an escaped line
                    if "(" in line.split("#")[0] and ")" not in line.split("#")[0]:
                        import_string += "\n" + line

                        while not line.split("#")[0].strip().endswith(")"):
                            try:
                                index, next_line = next(indexed_input)
                            except StopIteration:
                                break
                            line, _ = parse_comments(next_line)
                            import_string += "\n" + line

                    if import_string.strip().endswith(
                        (" import", " cimport")
                    ) or line.strip().startswith(("import ", "cimport ")):
                        import_string += "\n" + line
                    else:
                        import_string = import_string.rstrip().rstrip("\\") + " " + line.lstrip()

            if type_of_import == "from":
                import_string = (
                    import_string.replace("import(", "import (")
                    .replace("\\", " ")
                    .replace("\n", " ")
                )
                parts = import_string.split(" cimport " if cimports else " import ")

                from_import = parts[0].split(" ")
                import_string = (" cimport " if cimports else " import ").join(
                    [from_import[0] + " " + "".join(from_import[1:])] + parts[1:]
                )

            just_imports = [
                item.replace("{|", "{ ").replace("|}", " }")
                for item in _strip_syntax(import_string).split()
            ]

            direct_imports = just_imports[1:]
            top_level_module = ""
            if "as" in just_imports and (just_imports.index("as") + 1) < len(just_imports):
                while "as" in just_imports:
                    attribute = None
                    as_index = just_imports.index("as")
                    if type_of_import == "from":
                        attribute = just_imports[as_index - 1]
                        top_level_module = just_imports[0]
                        module = top_level_module + "." + attribute
                        alias = just_imports[as_index + 1]
                        direct_imports.remove(attribute)
                        direct_imports.remove(alias)
                        direct_imports.remove("as")
                        just_imports[1:] = direct_imports
                        if attribute == alias and config.remove_redundant_aliases:
                            pass
                        else:
                            yield IdentifiedImport(
                                index,
                                indented,
                                top_level_module,
                                attribute,
                                alias=alias,
                                cimport=cimports,
                            )

                    else:
                        module = just_imports[as_index - 1]
                        alias = just_imports[as_index + 1]
                        if not (module == alias and config.remove_redundant_aliases):
                            yield IdentifiedImport(index, indented, module, alias, cimport=cimports)

            else:
                if type_of_import == "from":
                    module = just_imports.pop(0)
                    for attribute in just_imports:
                        yield IdentifiedImport(index, indented, module, attribute)
                else:
                    for module in just_imports:
                        yield IdentifiedImport(index, indented, module, cimport=cimports)

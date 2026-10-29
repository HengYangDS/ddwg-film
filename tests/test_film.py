"""The film declaration, its refusals, and the engine boundary it draws."""

import re
import shutil
from pathlib import Path

import pytest

import filmkit.film as film
import filmkit.repository as repository
from filmkit.film import FilmError
from filmkit.production import CODES, Edition

# Han characters and CJK or full-width punctuation.
CHINESE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")


@pytest.fixture
def declared(tmp_path):
    """A copy of this film's declaration and every file it names, below a new root."""
    for _field, path in film.named_files(film.FILM):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repository.ROOT / path, target)
    shutil.copy2(repository.ROOT / film.DECLARATION, tmp_path / film.DECLARATION)
    return tmp_path


def rewrite(root: Path, old: str, new: str) -> None:
    """Replace one text of the declaration at a root."""
    path = root / film.DECLARATION
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def test_a_complete_declaration_loads(declared):
    assert film.load(declared) == film.FILM
    assert tuple(film.FILM.editions) == CODES


def test_a_missing_script_refuses_naming_its_edition(declared):
    (declared / Edition("en").script).unlink()
    with pytest.raises(FilmError, match=r"editions\.en\.sources: content/en/film-script\.json"):
        film.load(declared)


def test_invalid_fields_refuse_naming_each_field(declared):
    rewrite(declared, f'slug = "{film.FILM.slug}"', 'slug = "Two Words"')
    rewrite(declared, "overall_minimum = 90", "overall_minimum = 190")
    with pytest.raises(FilmError) as refusal:
        film.load(declared)
    assert "slug" in str(refusal.value)
    assert "review.overall_minimum" in str(refusal.value)


def test_an_unknown_field_refuses(declared):
    rewrite(declared, "[review]", 'title = "Another"\n\n[review]')
    with pytest.raises(FilmError, match="title"):
        film.load(declared)


def test_both_editions_are_declared(declared):
    rewrite(declared, "[editions.en]", "[editions.fr]")
    with pytest.raises(FilmError, match="editions"):
        film.load(declared)


def identities() -> set[str]:
    """What names this film.

    Its file prefix, delivery folder and source, and each edition's title, title parts,
    author and chapter titles.
    """
    names = {film.FILM.slug, film.FILM.documents_folder}
    source = repository.read(film.FILM.source_manifest)["repository"]
    names |= {source, source.rstrip("/").rsplit("/", 1)[-1]}
    for code in CODES:
        script = repository.read(Edition(code).script)
        names |= {script["title"], *script["title"].split(" · "), script["author"]}
        names |= {chapter["title"] for chapter in script["chapters"]}
    return names


def test_the_engine_names_no_film():
    found = []
    for path in sorted((repository.ROOT / "src/filmkit").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8").casefold()
        found += [
            f"{path.relative_to(repository.ROOT)}: {name}"
            for name in sorted(identities())
            if name.casefold() in text
        ]
    assert found == []


def test_each_edition_has_its_own_player():
    for code in CODES:
        player = (repository.ROOT / Edition(code).player).read_text()
        assert player.count("/*CHAPTERS*/[]") == 1
        assert player.count("/*TRANSCRIPT*/") == 1
        assert f'data-file="{Edition(code).prefix}-1080p-captioned.mp4"' in player


def test_the_english_player_keeps_no_chinese_text():
    assert CHINESE.search((repository.ROOT / Edition("en").player).read_text()) is None

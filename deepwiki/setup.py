"""cli-web-deepwiki — setup.py

Hybrid Python+Node CLI for DeepWiki. The Node sidecar lives at
`cli_web/deepwiki/unified_engine/` and is bundled as package_data.
After install, run:

    cli-web-deepwiki-install-engine

to npm-install the sidecar's deps (or simply: cd to the engine dir and
run `npm install`).
"""
from setuptools import find_namespace_packages, setup


with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="cli-web-deepwiki",
    version="0.1.0",
    description=(
        "Agent-native CLI for DeepWiki: search, fetch, parse, and convert "
        "wikis to Obsidian vaults via the unified.js ecosystem."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="cli-anything-web",
    license="MIT",
    packages=find_namespace_packages(include=["cli_web", "cli_web.*"]),
    package_data={
        "cli_web.deepwiki": [
            "*.md",
            "skills/*.md",
            "unified_engine/*.js",
            "unified_engine/*.json",
            "unified_engine/*.md",
            "unified_engine/pipelines/*.js",
            "unified_engine/plugins/*.js",
            "unified_engine/lib/*.js",
            "unified_engine/schemas/*.ts",
            "unified_engine/schemas/*.js",
        ],
    },
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=[
        "click>=8.1",
        "httpx>=0.27",
        "rich>=13.0",
        "prompt_toolkit>=3.0",
        "PyYAML>=6.0",
    ],
    extras_require={
        "browser": ["playwright>=1.40.0"],
        "dev": [
            "pytest>=7",
            "pytest-asyncio>=0.21",
            "pytest-mock>=3.10",
            "ruff>=0.1",
        ],
    },
    entry_points={
        "console_scripts": [
            # Primary short alias
            "dw=cli_web.deepwiki.deepwiki_cli:main",
            # Long form for cli-anything-web convention compatibility
            "cli-web-deepwiki=cli_web.deepwiki.deepwiki_cli:main",
            # Installer for the Node sidecar
            "dw-install-engine=cli_web.deepwiki.scripts.install_engine:main",
            "cli-web-deepwiki-install-engine=cli_web.deepwiki.scripts.install_engine:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Documentation",
        "Topic :: Text Processing :: Markup :: Markdown",
    ],
)

from starter_pack_scanner.checks.docs_location import DocsLocationCheck
from starter_pack_scanner.checks.readme_docs_link import ReadmeDocsLinkCheck
from starter_pack_scanner.checks.readme_rtd_badge import ReadmeRtdBadgeCheck
from starter_pack_scanner.checks.version_check import VersionCheck

ALL_CHECKS = [
    DocsLocationCheck,
    VersionCheck,
    ReadmeDocsLinkCheck,
    ReadmeRtdBadgeCheck,
]

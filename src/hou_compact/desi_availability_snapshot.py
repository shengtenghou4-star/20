"""Immutable DESI DR1 MWS single-epoch availability snapshot for the v7/v9 seed cohort.

The snapshot contains only survey/program/HEALPix file availability, never Gaia source IDs
or candidate-level measurements. It was derived from the successful 12,099-URL metadata
probe in encrypted relay run 29856569461. Gaia v7 and v9 returned identical ordered
source-ID cohorts, so this public coverage cache applies to both frozen queries.
"""

from __future__ import annotations

from dataclasses import dataclass

DESI_MWS_BASE_URL = "https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0"
DESI_SINGLE_EPOCH_RUN = "240521"
SNAPSHOT_SOURCE_PROBE_SHA256 = "e767d203dbce89f38fee7894a057fd0b588103f32e936b65032d315b073cdffa"
SNAPSHOT_RUN_ID = "29856569461"
SNAPSHOT_EXPECTED_URLS = 12099
SNAPSHOT_EXISTING_FILES = 618
SNAPSHOT_COHORT_ROWS = 5000

MAIN_BRIGHT_HEALPIX: tuple[int, ...] = (
    2063, 2196, 4118, 4136, 4139, 4162, 4164, 4282, 4291, 4334, 4610, 4612,
    4615, 4646, 4750, 5002, 5058, 5529, 5728, 5764, 5769, 5833, 5995, 5998,
    6083, 6121, 6242, 6270, 6480, 6495, 6569, 6581, 6729, 6740, 6772, 6957,
    7007, 7017, 7056, 7106, 7111, 7117, 7139, 7153, 7160, 7178, 7190, 7200,
    7411, 7447, 7454, 7581, 7586, 7739, 7759, 7787, 7835, 7866, 7888, 7896,
    7899, 7936, 7972, 7986, 8022, 8025, 8089, 8104, 8235, 8490, 8514, 8566,
    8569, 8573, 8634, 8688, 8694, 8869, 8879, 9036, 9137, 9193, 9203, 9408,
    9507, 9536, 9556, 9591, 9599, 9696, 9714, 9746, 9747, 10224, 10263, 10343,
    10434, 10653, 10665, 10674, 10716, 10798, 10822, 11040, 11141, 11238, 11288, 11326,
    11368, 11643, 11760, 12004, 12336, 12345, 12545, 12603, 12652, 12674, 12680, 13331,
    13334, 13337, 13411, 13457, 13461, 14988, 15010, 15236, 15283, 15306, 15326, 15913,
    16031, 16034, 16120, 17730, 17876, 18049, 18094, 18729, 18938, 19127, 19134, 19197,
    19327, 19458, 19879, 19904, 20072, 20078, 20115, 20142, 20200, 20220, 20354, 21777,
    21828, 21829, 21854, 21859, 21866, 21881, 21952, 21974, 22011, 22355, 22363, 22646,
    22734, 22741, 23044, 25469, 25587, 25830, 26142, 26178, 26254, 26380, 26439, 26843,
    27255, 27286, 27292, 27324, 27571, 27576, 27689, 27930, 29973, 30035, 30041, 30070,
    30078, 30079, 31155, 31294, 31390, 31488, 31504, 31515, 31529, 31560, 31568, 31575,
    31619, 31672, 31675, 31703, 31727, 31971, 31976, 32268, 32279, 32328, 32339, 32351,
    32425, 32426, 32434, 32453, 32456, 32459, 32500, 32511, 32521, 32538, 32567, 32664,
    32733, 32741, 32750, 40807, 40823, 40909, 49121, 49147,
)

MAIN_DARK_HEALPIX: tuple[int, ...] = (
    665, 2063, 2196, 4118, 4136, 4139, 4162, 4164, 4282, 4291, 4334, 4340,
    4610, 4612, 4615, 4646, 4750, 4904, 4998, 5002, 5018, 5354, 5529, 5728,
    5764, 5833, 6242, 6270, 6427, 6480, 6569, 6581, 6729, 6740, 6772, 6957,
    7017, 7056, 7106, 7111, 7139, 7153, 7160, 7178, 7200, 7364, 7411, 7586,
    7734, 7759, 7769, 7771, 7866, 7936, 7972, 8235, 8490, 8514, 8566, 8569,
    8573, 8634, 8688, 8694, 9036, 9137, 9193, 9203, 9408, 9507, 9536, 9556,
    9591, 9599, 9696, 9714, 9746, 9747, 10343, 10434, 10653, 10665, 10798, 10822,
    10939, 11040, 12336, 12345, 12545, 12603, 13331, 13334, 13337, 13411, 13457, 13461,
    14988, 15010, 15226, 15227, 15283, 15306, 15313, 15913, 16031, 16735, 16862, 17485,
    17538, 17730, 17876, 17921, 17955, 18049, 18094, 18399, 18938, 19127, 19134, 19327,
    19458, 19648, 19659, 19879, 19904, 20072, 20078, 20115, 20142, 20148, 20200, 20213,
    20220, 20354, 21777, 21828, 21829, 21854, 21859, 21866, 21881, 21952, 21974, 22011,
    22355, 22363, 22607, 22646, 22734, 22741, 23044, 25469, 25587, 25830, 26142, 26178,
    26254, 26380, 26439, 26843, 27255, 27286, 27292, 27324, 27571, 27576, 27689, 29973,
    29981, 30035, 30041, 30070, 30078, 30079, 31155, 31294, 31390, 31488, 31504, 31515,
    31529, 31560, 31568, 31575, 31619, 31672, 31675, 31703, 31727, 31971, 31976, 32268,
    32279, 32328, 32339, 32351, 32425, 32426, 32434, 32453, 32456, 32459, 32500, 32511,
    32521, 32538, 32567, 32664, 32733, 32741, 32750, 36677, 40807, 40823, 40909, 49121,
    49147,
)

MAIN_BACKUP_HEALPIX: tuple[int, ...] = (
    3517, 3555, 3583, 3868, 3870, 3913, 3951, 4039, 4162, 4164, 5058, 5352,
    5354, 5639, 5995, 5998, 6083, 6121, 6666, 7447, 7454, 7581, 7899, 7986,
    8025, 8104, 8136, 8490, 8569, 8573, 8694, 9036, 9203, 9408, 9746, 9747,
    10263, 10434, 10653, 10665, 10674, 10716, 10798, 11040, 11141, 11238, 12004, 13178,
    13180, 13182, 13183, 13251, 13252, 13259, 13270, 13281, 14466, 14492, 14538, 14560,
    17876, 19134, 20661, 20706, 20756, 20759, 20761, 20764, 20767, 20801, 20809, 20924,
    20963, 20969, 21312, 21580, 21586, 21588, 21592, 21597, 21628, 21629, 21701, 21709,
    21726, 21755, 21769, 21771, 21792, 21816, 21890, 21899, 21914, 21925, 21936, 21937,
    21952, 22101, 22294, 24043, 24388, 24406, 24410, 24414, 24437, 25469, 26178, 26254,
    27255, 27286, 27292, 27689, 30035, 30041, 30379, 30847, 30916, 30935, 30945, 31080,
    31137, 31155, 31169, 31282, 31294, 31390, 31488, 31504, 31515, 31560, 31568, 31575,
    32173, 32180, 32232, 32500, 32516, 32537, 32538, 39871, 40125, 40126, 40167, 40168,
    40178, 40402, 40469, 40470, 40472, 40474, 40475, 40497, 40498, 40499, 40500, 40502,
    40656, 40663, 40696, 40702, 40739, 40748, 40777, 40804, 40866,
)


@dataclass(frozen=True, order=True)
class SnapshotFile:
    survey: str
    program: str
    healpix: int

    @property
    def url(self) -> str:
        parent = self.healpix // 100
        filename = f"rvtab_spectra-{self.survey}-{self.program}-{self.healpix}.fits"
        return (
            f"{DESI_MWS_BASE_URL}/rv_output/{DESI_SINGLE_EPOCH_RUN}/healpix/"
            f"{self.survey}/{self.program}/{parent}/{self.healpix}/{filename}"
        )


def iter_snapshot_files(*, include_backup: bool = False) -> tuple[SnapshotFile, ...]:
    """Return the frozen existing-file list with non-backup programs first."""
    groups = [
        ("main", "bright", MAIN_BRIGHT_HEALPIX),
        ("main", "dark", MAIN_DARK_HEALPIX),
    ]
    if include_backup:
        groups.append(("main", "backup", MAIN_BACKUP_HEALPIX))
    return tuple(
        SnapshotFile(survey, program, healpix)
        for survey, program, healpixels in groups
        for healpix in healpixels
    )


def snapshot_healpix(*, include_backup: bool = False) -> frozenset[int]:
    """Return HEALPix cells with at least one available frozen DESI file."""
    return frozenset(
        item.healpix for item in iter_snapshot_files(include_backup=include_backup)
    )


def validate_snapshot() -> None:
    """Fail if the embedded snapshot metadata and lists are internally inconsistent."""
    all_files = iter_snapshot_files(include_backup=True)
    if len(all_files) != SNAPSHOT_EXISTING_FILES:
        raise RuntimeError(
            f"snapshot file count mismatch: {len(all_files)} != {SNAPSHOT_EXISTING_FILES}"
        )
    keys = {(item.survey, item.program, item.healpix) for item in all_files}
    if len(keys) != len(all_files):
        raise RuntimeError("snapshot contains duplicate survey/program/HEALPix rows")

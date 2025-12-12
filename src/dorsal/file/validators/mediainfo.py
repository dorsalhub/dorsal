# Copyright 2025 Dorsal Hub LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import logging
import re
from typing import Annotated, Any, ClassVar
from typing_extensions import Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from dorsal.common.validators import TString4096


logger = logging.getLogger(__name__)


RX_RATIO_FLOAT = re.compile(
    r"^(?P<first>[+-]?(?:\d*\.)?[\d]+)\s*?\/\s*?(?:[+-]?(?:\d*\.)?[\d]+)$"
)  # 4/12, 445 / 91, 1.999 / 1.999

RX_RATIO_INTEGER = re.compile(r"^(?P<first>[+-]?[\d]+)\s*?\/\s*?(?:[+-]?(?:\d*\.)?[\d]+)$")  # 4/12, 445 / 91


def coerce_integer(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            # handle strings in ratio form, e.g. '3/12' -> return 3
            if match := RX_RATIO_INTEGER.match(value.strip()):
                return int(match.groupdict()["first"])
    logger.debug("Returning `None` for invalid integer field: %s", value)
    return None


def coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            # handle strings in ratio form, e.g. '3/12' -> return 3
            if match := RX_RATIO_FLOAT.match(value.strip()):
                return float(match.groupdict()["first"])
    logger.debug("Returning `None` for invalid float field: %s", value)
    return None


CoerceInteger = Annotated[int | None, BeforeValidator(coerce_integer)]
CoerceFloat = Annotated[float | None, BeforeValidator(coerce_float)]


class MediaInfoTrackExtra(BaseModel):
    """
    Handle arbitrary extra key-value pairs from MediaInfo tracks.

    - Truncate string values and keys to defined maximum lengths.
    - Convert specific complex structures (e.g., ConformanceErrors) to string.
    - Limit the total number of extra fields.
    """

    MAX_EXTRA_FIELD_COUNT: ClassVar[int] = 256
    MAX_EXTRA_KEY_LENGTH: ClassVar[int] = 256
    MAX_EXTRA_VALUE_LENGTH: ClassVar[int] = 4096

    @model_validator(mode="after")
    def process_and_limit_extra_fields(self) -> Self:
        """Process and limit extra fields after initial model validation."""
        if not self.model_extra:
            return self

        processed_extra: dict[str, str | None] = {}
        limited_extra_items = list(self.model_extra.items())[: self.MAX_EXTRA_FIELD_COUNT]
        if len(self.model_extra) > self.MAX_EXTRA_FIELD_COUNT:
            logger.debug(
                "Reached MAX_EXTRA_FIELD_COUNT (%d). Only the first %d extra fields will be processed.",
                self.MAX_EXTRA_FIELD_COUNT,
                self.MAX_EXTRA_FIELD_COUNT,
            )

        for original_key, value in limited_extra_items:
            truncated_key = original_key
            if len(original_key) > self.MAX_EXTRA_KEY_LENGTH:
                truncated_key = original_key[: self.MAX_EXTRA_KEY_LENGTH]
                logger.debug(
                    "Truncated extra field key from '%s' to '%s'.",
                    original_key,
                    truncated_key,
                )

            processed_value: str | None
            if isinstance(value, str):
                processed_value = value[: self.MAX_EXTRA_VALUE_LENGTH]
                if len(value) > self.MAX_EXTRA_VALUE_LENGTH:
                    logger.debug("Truncated string value for extra field '%s'.", truncated_key)
            elif original_key == "ConformanceErrors":
                processed_value = str(value)[: self.MAX_EXTRA_VALUE_LENGTH]
                logger.debug(
                    "Converted and truncated 'ConformanceErrors' value for extra field '%s'.",
                    truncated_key,
                )
            elif isinstance(value, dict) and "#value" in value and isinstance(value["#value"], str):
                original_inner_value = value["#value"]
                processed_value = original_inner_value[: self.MAX_EXTRA_VALUE_LENGTH]
                if len(original_inner_value) > self.MAX_EXTRA_VALUE_LENGTH:
                    logger.debug(
                        "Extracted and truncated '#value' for extra field '%s'.",
                        truncated_key,
                    )
            else:
                logger.debug(
                    "Cannot publish non-string/non-standard 'extra' field '%s' (type: %s). Setting to None.",
                    truncated_key,
                    type(value).__name__,
                )
                processed_value = None

            if truncated_key in processed_extra:
                logger.warning(
                    "Duplicate truncated key '%s' encountered in extra fields after key truncation. Overwriting.",
                    truncated_key,
                )
            processed_extra[truncated_key] = processed_value

        self.model_extra.clear()
        self.model_extra.update(processed_extra)
        return self

    model_config = ConfigDict(extra="allow")


class MediaInfoTrack(BaseModel):
    """
    Define structure for individual MediaInfo tracks (General, Video, Audio, etc.).
    Fields are optional, using custom types for coercion and truncation.
    """

    Accompaniment: TString4096 | None = None
    ActiveFormatDescription: TString4096 | None = None
    Actor: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Actor_Character: TString4096 | None = None
    Added_Date: TString4096 | datetime.datetime | None = None
    Album: TString4096 | None = None
    Album_More: TString4096 | None = None
    Album_Performer: TString4096 | None = None
    Album_Performer_Sort: TString4096 | None = None
    Album_ReplayGain_Gain: TString4096 | None = None
    Album_ReplayGain_Peak: TString4096 | None = None
    Active_DisplayAspectRatio: CoerceFloat = None
    Active_Height: CoerceInteger = None
    Active_Width: CoerceInteger = None
    ActiveFormatDescription_MuxingMode: TString4096 | None = None
    ActiveFormatDescription_String: TString4096 | None = None
    Album_Performer_Url: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Album_ReplayGain_Gain_String: TString4096 | None = None
    Album_Sort: TString4096 | None = None
    Alignment: TString4096 | None = None
    Alignment_String: TString4096 | None = None
    AlternateGroup: TString4096 | None = None
    AlternateGroup_String: TString4096 | None = None
    Archival_Location: TString4096 | None = None
    Arranger: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    ArtDirector: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    AssistantDirector: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Audio_Codec_List: TString4096 | None = None
    AudioCount: CoerceInteger = None
    Audio_Channels_Total: CoerceInteger = None
    Audio_Format_List: TString4096 | None = None
    Audio_Format_WithHint_List: TString4096 | None = None
    Audio_Language_List: TString4096 | None = None
    BarCode: TString4096 | None = None
    BitDepth_Detected: CoerceInteger = None
    BitDepth_Detected_String: TString4096 | None = None
    BitDepth: CoerceInteger = None
    BitDepth_Stored: CoerceInteger = None
    BitDepth_Stored_String: TString4096 | None = None
    BitDepth_String: TString4096 | None = None
    BitRate_Encoded: CoerceFloat = None
    BitRate_Encoded_String: TString4096 | None = None
    BitRate_Maximum: CoerceFloat = None
    BitRate_Maximum_String: TString4096 | None = None
    BitRate_Minimum: CoerceFloat = None
    BitRate_Minimum_String: TString4096 | None = None
    BitRate: CoerceFloat = None
    BitRate_Mode: TString4096 | None = None
    BitRate_Mode_String: TString4096 | None = None
    BitRate_Nominal: CoerceFloat = None
    BitRate_Nominal_String: TString4096 | None = None
    BitRate_String: TString4096 | None = None
    Bits_Pixel_Frame: CoerceFloat = Field(default=None, alias="Bits-Pixel_Frame")
    BitsPixel_Frame: CoerceFloat = None
    BPM: TString4096 | None = None
    BufferSize: TString4096 | None = None
    CatalogNumber: TString4096 | None = None
    ChannelLayoutID: TString4096 | None = None
    ChannelLayout: TString4096 | None = None
    ChannelLayout_Original: TString4096 | None = None
    ChannelPositions: TString4096 | None = None
    ChannelPositions_Original: TString4096 | None = None
    ChannelPositions_Original_String2: TString4096 | None = None
    ChannelPositions_String2: TString4096 | None = None
    Channels: CoerceInteger = None
    Channels_Original: CoerceInteger = None
    Channels_Original_String: TString4096 | None = None
    Channels_String: TString4096 | None = None
    Chapter: TString4096 | None = None
    Chapters_Pos_Begin: CoerceInteger = None
    Chapters_Pos_End: CoerceInteger = None
    Choregrapher: TString4096 | None = None
    ChromaSubsampling: TString4096 | None = None
    ChromaSubsampling_Position: TString4096 | None = None
    ChromaSubsampling_String: TString4096 | None = None
    Codec_CC: TString4096 | None = None
    Codec_Description: TString4096 | None = None
    Codec_Extensions: TString4096 | None = None
    Codec_Family: TString4096 | None = None
    CodecID_Compatible: TString4096 | None = None
    CodecID_Description: TString4096 | None = None
    CodecID_Hint: TString4096 | None = None
    CodecID_Info: TString4096 | None = None
    CodecID: TString4096 | None = None
    CodecID_String: TString4096 | None = None
    CodecID_Url: TString4096 | None = None
    CodecID_Version: TString4096 | None = None
    Codec_Info: TString4096 | None = None
    Codec: TString4096 | None = None
    Codec_Profile: TString4096 | None = None
    Codec_Settings_Automatic: TString4096 | None = None
    Codec_Settings_BVOP: TString4096 | None = None
    Codec_Settings_CABAC: TString4096 | None = None
    Codec_Settings_Endianness: TString4096 | None = None
    Codec_Settings_Firm: TString4096 | None = None
    Codec_Settings_Floor: TString4096 | None = None
    Codec_Settings_GMC: TString4096 | None = None
    Codec_Settings_GMC_String: TString4096 | None = None
    Codec_Settings_ITU: TString4096 | None = None
    Codec_Settings_Law: TString4096 | None = None
    Codec_Settings_Matrix_Data: TString4096 | None = None
    Codec_Settings_Matrix: TString4096 | None = None
    Codec_Settings: TString4096 | None = None
    Codec_Settings_PacketBitStream: TString4096 | None = None
    Codec_Settings_QPel: TString4096 | None = None
    Codec_Settings_RefFrames: TString4096 | None = None
    Codec_Settings_Sign: TString4096 | None = None
    Codec_String: TString4096 | None = None
    Codec_Url: TString4096 | None = None
    CoDirector: TString4096 | None = None
    Collection: TString4096 | None = None
    Colorimetry: TString4096 | None = None
    ColorSpace: TString4096 | None = None
    colour_description_present: TString4096 | None = None
    colour_description_present_Original: TString4096 | None = None
    colour_description_present_Original_Source: TString4096 | None = None
    colour_description_present_Source: TString4096 | None = None
    colour_primaries: TString4096 | None = None
    colour_primaries_Original: TString4096 | None = None
    colour_primaries_Original_Source: TString4096 | None = None
    colour_primaries_Source: TString4096 | None = None
    colour_range: TString4096 | None = None
    colour_range_Original: TString4096 | None = None
    colour_range_Original_Source: TString4096 | None = None
    colour_range_Source: TString4096 | None = None
    Comic: TString4096 | None = None
    Comic_More: TString4096 | None = None
    Comic_Position_Total: CoerceInteger = None
    Comment: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    CommissionedBy: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Compilation: TString4096 | None = None
    Compilation_String: TString4096 | None = None
    # CompleteName_Last: Potential PII - intentionally skipped
    # CompleteName: Potential PII - intentionally skipped
    Composer: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Composer_Nationality: TString4096 | None = None
    Composer_Sort: TString4096 | None = None
    Compression_Mode: TString4096 | None = None
    Compression_Mode_String: TString4096 | None = None
    Compression_Ratio: CoerceFloat = None
    Conductor: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    ContentType: TString4096 | None = None
    CoProducer: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Copyright: TString4096 | None = None
    Copyright_Url: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    CostumeDesigner: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Count: CoerceInteger = None
    Countries: TString4096 | None = None
    Country: TString4096 | None = None
    Cover_Data: TString4096 | None = None
    Cover_Description: TString4096 | None = None
    Cover_Mime: TString4096 | None = None
    Cover: TString4096 | None = None
    Cover_Type: TString4096 | None = None
    Cropped: TString4096 | None = None
    DataSize: CoerceInteger = None
    Default: TString4096 | None = None
    Default_String: TString4096 | None = None
    Delay_DropFrame: TString4096 | None = None
    Delay: CoerceFloat = None
    Delay_Original_DropFrame: TString4096 | None = None
    Delay_Original: CoerceFloat = None
    Delay_Original_Settings: TString4096 | None = None
    Delay_Original_Source: TString4096 | None = None
    Delay_Original_String1: TString4096 | None = None
    Delay_Original_String2: TString4096 | None = None
    Delay_Original_String3: TString4096 | None = None
    Delay_Original_String4: TString4096 | None = None
    Delay_Original_String5: TString4096 | None = None
    Delay_Original_String: TString4096 | None = None
    Delay_Settings: TString4096 | None = None
    Delay_Source: TString4096 | None = None
    Delay_Source_String: TString4096 | None = None
    Delay_String1: TString4096 | None = None
    Delay_String2: TString4096 | None = None
    Delay_String3: TString4096 | None = None
    Delay_String4: TString4096 | None = None
    Delay_String5: TString4096 | None = None
    Delay_String: TString4096 | None = None
    Description: TString4096 | None = None
    Dimensions: TString4096 | None = None
    Director: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    DirectorOfPhotography: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Disabled: TString4096 | None = None
    Disabled_String: TString4096 | None = None
    DisplayAspectRatio_CleanAperture: CoerceFloat = None
    DisplayAspectRatio_CleanAperture_String: TString4096 | None = None
    DisplayAspectRatio: CoerceFloat = None
    DisplayAspectRatio_Original: CoerceFloat = None
    DisplayAspectRatio_Original_String: TString4096 | None = None
    DisplayAspectRatio_String: TString4096 | None = None
    DistributedBy: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    DolbyVision_Layers: TString4096 | None = None
    DolbyVision_Profile: TString4096 | None = None
    DolbyVision_Version: TString4096 | None = None
    Domain: TString4096 | None = None
    DotsPerInch: TString4096 | None = None
    Duration_Base: TString4096 | None = None
    Duration_End_Command: CoerceFloat = None
    Duration_End_Command_String1: TString4096 | None = None
    Duration_End_Command_String2: TString4096 | None = None
    Duration_End_Command_String3: TString4096 | None = None
    Duration_End_Command_String4: TString4096 | None = None
    Duration_End_Command_String5: TString4096 | None = None
    Duration_End_Command_String: TString4096 | None = None
    Duration_End: CoerceFloat = None
    Duration_End_String1: TString4096 | None = None
    Duration_End_String2: TString4096 | None = None
    Duration_End_String3: TString4096 | None = None
    Duration_End_String4: TString4096 | None = None
    Duration_End_String5: TString4096 | None = None
    Duration_End_String: TString4096 | None = None
    Duration_FirstFrame: CoerceFloat = None
    Duration_FirstFrame_String1: TString4096 | None = None
    Duration_FirstFrame_String2: TString4096 | None = None
    Duration_FirstFrame_String3: TString4096 | None = None
    Duration_FirstFrame_String4: TString4096 | None = None
    Duration_FirstFrame_String5: TString4096 | None = None
    Duration_FirstFrame_String: TString4096 | None = None
    Duration_LastFrame: CoerceFloat = None
    Duration_LastFrame_String1: TString4096 | None = None
    Duration_LastFrame_String2: TString4096 | None = None
    Duration_LastFrame_String3: TString4096 | None = None
    Duration_LastFrame_String4: TString4096 | None = None
    Duration_LastFrame_String5: TString4096 | None = None
    Duration_LastFrame_String: TString4096 | None = None
    Duration: CoerceFloat = None
    Duration_Start2End: CoerceFloat = None
    Duration_Start2End_String1: TString4096 | None = None
    Duration_Start2End_String2: TString4096 | None = None
    Duration_Start2End_String3: TString4096 | None = None
    Duration_Start2End_String4: TString4096 | None = None
    Duration_Start2End_String5: TString4096 | None = None
    Duration_Start2End_String: TString4096 | None = None
    Duration_Start_Command: CoerceFloat = None
    Duration_Start_Command_String1: TString4096 | None = None
    Duration_Start_Command_String2: TString4096 | None = None
    Duration_Start_Command_String3: TString4096 | None = None
    Duration_Start_Command_String4: TString4096 | None = None
    Duration_Start_Command_String5: TString4096 | None = None
    Duration_Start_Command_String: TString4096 | None = None
    Duration_Start: CoerceFloat = None
    Duration_Start_String1: TString4096 | None = None
    Duration_Start_String2: TString4096 | None = None
    Duration_Start_String3: TString4096 | None = None
    Duration_Start_String4: TString4096 | None = None
    Duration_Start_String5: TString4096 | None = None
    Duration_Start_String: TString4096 | None = None
    Duration_String1: TString4096 | None = None
    Duration_String2: TString4096 | None = None
    Duration_String3: TString4096 | None = None
    Duration_String4: TString4096 | None = None
    Duration_String5: TString4096 | None = None
    Duration_String: TString4096 | None = None
    EditedBy: TString4096 | None = None
    ElementCount: CoerceInteger = None
    Encoded_Application_CompanyName: TString4096 | None = None
    Encoded_Application: TString4096 | None = None
    Encoded_Application_Name: TString4096 | None = None
    Encoded_Application_String: TString4096 | None = None
    Encoded_Application_Url: TString4096 | None = None
    Encoded_Application_Version: TString4096 | None = None
    EncodedBy: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Encoded_Date: TString4096 | datetime.datetime | None = None
    Encoded_Library_CompanyName: TString4096 | None = None
    Encoded_Library_Date: TString4096 | datetime.datetime | None = None
    Encoded_Library: TString4096 | None = None
    Encoded_Library_Name: TString4096 | None = None
    Encoded_Library_Settings: TString4096 | None = None
    Encoded_Library_String: TString4096 | None = None
    Encoded_Library_Version: TString4096 | None = None
    Encoded_OperatingSystem: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Encryption_Format: TString4096 | None = None
    Encryption_InitializationVector: TString4096 | None = None
    Encryption_Length: TString4096 | None = None
    Encryption_Method: TString4096 | None = None
    Encryption: TString4096 | None = None
    Encryption_Mode: TString4096 | None = None
    Encryption_Padding: TString4096 | None = None
    EPG_Positions_Begin: CoerceInteger = None
    EPG_Positions_End: CoerceInteger = None
    Events_MinDuration: CoerceFloat = None
    Events_MinDuration_String1: TString4096 | None = None
    Events_MinDuration_String2: TString4096 | None = None
    Events_MinDuration_String3: TString4096 | None = None
    Events_MinDuration_String4: TString4096 | None = None
    Events_MinDuration_String5: TString4096 | None = None
    Events_MinDuration_String: TString4096 | None = None
    Events_PaintOn: TString4096 | None = None
    Events_PopOn: TString4096 | None = None
    Events_RollUp: TString4096 | None = None
    Events_Total: TString4096 | None = None
    ExecutiveProducer: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    File_Created_Date_Local: TString4096 | None = None
    File_Created_Date: TString4096 | None = None
    FileExtension_Last: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    FileExtension: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    File_Modified_Date_Local: TString4096 | datetime.datetime | None = None
    File_Modified_Date: TString4096 | datetime.datetime | None = None
    FileNameExtension_Last: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    FileNameExtension: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    FileName_Last: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    FileName: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    FileSize: TString4096 | None = None
    FileSize_String1: TString4096 | None = None
    FileSize_String2: TString4096 | None = None
    FileSize_String3: TString4096 | None = None
    FileSize_String4: TString4096 | None = None
    FileSize_String: TString4096 | None = None
    FirstDisplay_Delay_Frames: TString4096 | None = None
    FirstDisplay_Type: TString4096 | None = None
    FirstPacketOrder: CoerceInteger = None
    # FolderName_Last: Potential PII - intentionally skipped
    # FolderName: Potential PII - intentionally skipped
    FooterSize: CoerceInteger = None
    Forced: TString4096 | None = None
    Forced_String: TString4096 | None = None
    Format_AdditionalFeatures: TString4096 | None = None
    Format_Commercial_IfAny: TString4096 | None = None
    Format_Commercial: TString4096 | None = None
    Format_Compression: TString4096 | None = None
    Format_Extensions: TString4096 | None = None
    Format_Info: TString4096 | None = None
    Format_Level: TString4096 | None = None
    Format: TString4096 | None = None
    Format_Profile: TString4096 | None = None
    Format_Settings_BVOP: TString4096 | None = None
    Format_Settings_BVOP_String: TString4096 | None = None
    Format_Settings_CABAC: TString4096 | None = None
    Format_Settings_CABAC_String: TString4096 | None = None
    Format_Settings_Emphasis: TString4096 | None = None
    Format_Settings_Endianness: TString4096 | None = None
    Format_Settings_Firm: TString4096 | None = None
    Format_Settings_Floor: TString4096 | None = None
    Format_Settings_FrameMode: TString4096 | None = None
    Format_Settings_GMC: CoerceInteger = None
    Format_Settings_GMC_String: TString4096 | None = None
    Format_Settings_GOP: TString4096 | None = None
    Format_Settings_ITU: TString4096 | None = None
    Format_Settings_Law: TString4096 | None = None
    Format_Settings_Matrix_Data: TString4096 | None = None
    Format_Settings_Matrix: TString4096 | None = None
    Format_Settings_Matrix_String: TString4096 | None = None
    Format_Settings: TString4096 | None = None
    Format_Settings_ModeExtension: TString4096 | None = None
    Format_Settings_Mode: TString4096 | None = None
    Format_Settings_Packing: TString4096 | None = None
    Format_Settings_PictureStructure: TString4096 | None = None
    Format_Settings_PS: TString4096 | None = None
    Format_Settings_PS_String: TString4096 | None = None
    Format_Settings_Pulldown: TString4096 | None = None
    Format_Settings_QPel: TString4096 | None = None
    Format_Settings_QPel_String: TString4096 | None = None
    Format_Settings_RefFrames: CoerceInteger = None
    Format_Settings_RefFrames_String: TString4096 | None = None
    Format_Settings_SBR: TString4096 | None = None
    Format_Settings_SBR_String: TString4096 | None = None
    Format_Settings_Sign: TString4096 | None = None
    Format_Settings_SliceCount: CoerceInteger = None
    Format_Settings_SliceCount_String: TString4096 | None = None
    Format_Settings_Wrapping: TString4096 | None = None
    Format_String: TString4096 | None = None
    Format_Tier: TString4096 | None = None
    Format_Url: TString4096 | None = None
    Format_Version: TString4096 | None = None
    FrameCount: CoerceInteger = None
    FrameRate_Den: CoerceInteger = None
    FrameRate_Maximum: CoerceFloat = None
    FrameRate_Maximum_String: TString4096 | None = None
    FrameRate_Minimum: CoerceFloat = None
    FrameRate_Minimum_String: TString4096 | None = None
    FrameRate: CoerceFloat = None
    FrameRate_Mode: TString4096 | None = None
    FrameRate_Mode_Original: TString4096 | None = None
    FrameRate_Mode_Original_String: TString4096 | None = None
    FrameRate_Mode_String: TString4096 | None = None
    FrameRate_Nominal: CoerceFloat = None
    FrameRate_Nominal_String: TString4096 | None = None
    FrameRate_Num: CoerceInteger = None
    FrameRate_Original_Den: CoerceFloat = None
    FrameRate_Original: CoerceFloat = None
    FrameRate_Original_Num: CoerceFloat = None
    FrameRate_Original_String: TString4096 | None = None
    FrameRate_Real: CoerceFloat = None
    FrameRate_Real_String: TString4096 | None = None
    FrameRate_String: TString4096 | None = None
    GeneralCount: CoerceInteger = None
    Genre: TString4096 | None = None
    Gop_OpenClosed_FirstFrame: TString4096 | None = None
    Gop_OpenClosed_FirstFrame_String: TString4096 | None = None
    Gop_OpenClosed: TString4096 | None = None
    Gop_OpenClosed_String: TString4096 | None = None
    Grouping: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    HDR_Format_Commercial: TString4096 | None = None
    HDR_Format_Compatibility: TString4096 | None = None
    HDR_Format_Level: TString4096 | None = None
    HDR_Format: TString4096 | None = None
    HDR_Format_Profile: TString4096 | None = None
    HDR_Format_Settings: TString4096 | None = None
    HDR_Format_String: TString4096 | None = None
    HDR_Format_Version: TString4096 | None = None
    HeaderSize: CoerceInteger = None
    Height_CleanAperture: CoerceInteger = None
    Height_CleanAperture_String: TString4096 | None = None
    Height: CoerceInteger = None
    Height_Offset: CoerceInteger = None
    Height_Offset_String: TString4096 | None = None
    Height_Original: CoerceInteger = None
    Height_Original_String: TString4096 | None = None
    Height_String: TString4096 | None = None
    ICRA: TString4096 | None = None
    ID: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    ID_String: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Image_Codec_List: TString4096 | None = None
    ImageCount: CoerceInteger = None
    Image_Format_List: TString4096 | None = None
    Image_Format_WithHint_List: TString4096 | None = None
    Image_Language_List: TString4096 | None = None
    Inform: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Interlacement: TString4096 | None = None
    Interlacement_String: TString4096 | None = None
    Interleaved: TString4096 | None = None
    Interleave_Duration: CoerceFloat = None
    Interleave_Duration_String: TString4096 | None = None
    Interleave_Preload: CoerceFloat = None
    Interleave_Preload_String: TString4096 | None = None
    Interleave_VideoFrames: CoerceFloat = None
    InternetMediaType: TString4096 | None = None
    ISBN: TString4096 | None = None
    ISRC: TString4096 | None = None
    IsStreamable: TString4096 | None = None
    Keywords: TString4096 | None = None
    LabelCode: TString4096 | None = None
    Label: TString4096 | None = None
    Language: TString4096 | None = None
    Language_More: TString4096 | None = None
    Language_String1: TString4096 | None = None
    Language_String2: TString4096 | None = None
    Language_String3: TString4096 | None = None
    Language_String4: TString4096 | None = None
    Language_String: TString4096 | None = None
    LawRating: TString4096 | None = None
    LawRating_Reason: TString4096 | None = None
    LCCN: TString4096 | None = None
    Lightness: TString4096 | None = None
    Lines_Count: TString4096 | None = None
    Lines_MaxCharacterCount: CoerceInteger = None
    Lines_MaxCountPerEvent: CoerceInteger = None
    List: TString4096 | None = None
    List_StreamKind: TString4096 | None = None
    List_StreamPos: TString4096 | None = None
    List_String: TString4096 | None = None
    Lyricist: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Lyrics: TString4096 | None = None
    MasteredBy: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Mastered_Date: TString4096 | datetime.datetime | None = None
    MasteringDisplay_ColorPrimaries: TString4096 | None = None
    MasteringDisplay_ColorPrimaries_Original: TString4096 | None = None
    MasteringDisplay_ColorPrimaries_Original_Source: TString4096 | None = None
    MasteringDisplay_ColorPrimaries_Source: TString4096 | None = None
    MasteringDisplay_Luminance: TString4096 | None = None
    MasteringDisplay_Luminance_Original: TString4096 | None = None
    MasteringDisplay_Luminance_Original_Source: TString4096 | None = None
    MasteringDisplay_Luminance_Source: TString4096 | None = None
    Matrix_ChannelPositions: TString4096 | None = None
    Matrix_ChannelPositions_String2: TString4096 | None = None
    Matrix_Channels: CoerceInteger = None
    Matrix_Channels_String: TString4096 | None = None
    matrix_coefficients: TString4096 | None = None
    matrix_coefficients_Original: TString4096 | None = None
    matrix_coefficients_Original_Source: TString4096 | None = None
    matrix_coefficients_Source: TString4096 | None = None
    Matrix_Format: TString4096 | None = None
    MaxCLL: TString4096 | None = None
    MaxCLL_Original: TString4096 | None = None
    MaxCLL_Original_Source: TString4096 | None = None
    MaxCLL_Source: TString4096 | None = None
    MaxFALL: TString4096 | None = None
    MaxFALL_Original: TString4096 | None = None
    MaxFALL_Original_Source: TString4096 | None = None
    MaxFALL_Source: TString4096 | None = None
    Menu_Codec_List: TString4096 | None = None
    MenuCount: CoerceInteger = None
    Menu_Format_List: TString4096 | None = None
    Menu_Format_WithHint_List: TString4096 | None = None
    MenuID: TString4096 | None = None
    MenuID_String: TString4096 | None = None
    Menu_Language_List: TString4096 | None = None
    Mood: TString4096 | None = None
    Movie_Country: TString4096 | None = None
    Movie: TString4096 | None = None
    Movie_More: TString4096 | None = None
    Movie_Url: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    MultiView_BaseProfile: TString4096 | None = None
    MultiView_Count: TString4096 | None = None
    MultiView_Layout: TString4096 | None = None
    MusicBy: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    MuxingMode: TString4096 | None = None
    MuxingMode_MoreInfo: TString4096 | None = None
    NetworkName: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Original_Album: TString4096 | None = None
    Original_Lyricist: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Original_Movie: TString4096 | None = None
    Original_NetworkName: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    OriginalNetworkName: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Original_Part: TString4096 | None = None
    Original_Performer: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Original_Released_Date: TString4096 | datetime.datetime | None = None
    OriginalSourceForm_Cropped: TString4096 | None = None
    OriginalSourceForm_DistributedBy: TString4096 | None = None
    OriginalSourceForm: TString4096 | None = None
    OriginalSourceForm_Name: TString4096 | None = None
    OriginalSourceForm_NumColors: TString4096 | None = None
    OriginalSourceForm_Sharpness: TString4096 | None = None
    OriginalSourceMedium_ID: TString4096 | None = None
    OriginalSourceMedium_ID_String: TString4096 | None = None
    OriginalSourceMedium: TString4096 | None = None
    Original_Track: TString4096 | None = None
    Other_Codec_List: TString4096 | None = None
    OtherCount: CoerceInteger = None
    Other_Format_List: TString4096 | None = None
    Other_Format_WithHint_List: TString4096 | None = None
    Other_Language_List: TString4096 | None = None
    OverallBitRate_Maximum: CoerceFloat = None
    OverallBitRate_Maximum_String: TString4096 | None = None
    OverallBitRate_Minimum: CoerceFloat = None
    OverallBitRate_Minimum_String: TString4096 | None = None
    OverallBitRate: CoerceFloat = None
    OverallBitRate_Mode: TString4096 | None = None
    OverallBitRate_Mode_String: TString4096 | None = None
    OverallBitRate_Nominal: CoerceFloat = None
    OverallBitRate_Nominal_String: TString4096 | None = None
    OverallBitRate_String: TString4096 | None = None
    Owner: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    PackageName: TString4096 | None = None
    Part: TString4096 | None = None
    Part_Position: CoerceInteger = None
    Part_Position_Total: CoerceInteger = None
    Performer: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Performer_Sort: TString4096 | None = None
    Performer_Url: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Period: TString4096 | None = None
    PixelAspectRatio_CleanAperture: CoerceFloat = None
    PixelAspectRatio_CleanAperture_String: TString4096 | None = None
    PixelAspectRatio: CoerceFloat = None
    PixelAspectRatio_Original: CoerceFloat = None
    PixelAspectRatio_Original_String: TString4096 | None = None
    PixelAspectRatio_String: TString4096 | None = None
    Played_Count: CoerceInteger = None
    Played_First_Date: TString4096 | datetime.datetime | None = None
    Played_Last_Date: TString4096 | datetime.datetime | None = None
    PodcastCategory: TString4096 | None = None
    Producer_Copyright: TString4096 | None = None
    Producer: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    ProductionDesigner: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    ProductionStudio: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Publisher: TString4096 | None = None
    Publisher_URL: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Rating: TString4096 | None = None
    Recorded_Date: TString4096 | datetime.datetime | None = None
    Recorded_Location: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Reel: TString4096 | None = None
    Reel_Position: CoerceInteger = None
    Reel_Position_Total: CoerceInteger = None
    Released_Date: TString4096 | datetime.datetime | None = None
    RemixedBy: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    ReplayGain_Gain: TString4096 | None = None
    ReplayGain_Gain_String: TString4096 | None = None
    ReplayGain_Peak: TString4096 | None = None
    Resolution: CoerceInteger = None
    Resolution_String: TString4096 | None = None
    Rotation: TString4096 | None = None
    Rotation_String: TString4096 | None = None
    Sampled_Height: CoerceInteger = None
    Sampled_Width: CoerceInteger = None
    SamplesPerFrame: CoerceFloat = None
    SamplingCount: CoerceInteger = None
    SamplingRate: CoerceFloat = None
    SamplingRate_String: TString4096 | None = None
    ScanOrder: TString4096 | None = None
    ScanOrder_Original: TString4096 | None = None
    ScanOrder_Original_String: TString4096 | None = None
    ScanOrder_StoredDisplayedInverted: TString4096 | None = None
    ScanOrder_Stored: TString4096 | None = None
    ScanOrder_Stored_String: TString4096 | None = None
    ScanOrder_String: TString4096 | None = None
    ScanType: TString4096 | None = None
    ScanType_Original: TString4096 | None = None
    ScanType_Original_String: TString4096 | None = None
    ScanType_StoreMethod_FieldsPerBlock: TString4096 | None = None
    ScanType_StoreMethod: TString4096 | None = None
    ScanType_StoreMethod_String: TString4096 | None = None
    ScanType_String: TString4096 | None = None
    ScreenplayBy: TString4096 | None = None
    Season: TString4096 | None = None
    Season_Position: CoerceInteger = None
    Season_Position_Total: CoerceInteger = None
    ServiceChannel: TString4096 | None = None
    ServiceKind: TString4096 | None = None
    ServiceKind_String: TString4096 | None = None
    ServiceName: TString4096 | None = None
    ServiceProvider: TString4096 | None = None
    ServiceProvider_Url: TString4096 | None = None
    ServiceType: TString4096 | None = None
    Service_Url: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    SoundEngineer: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Source_Duration_FirstFrame: CoerceFloat = None
    Source_Duration_FirstFrame_String1: TString4096 | None = None
    Source_Duration_FirstFrame_String2: TString4096 | None = None
    Source_Duration_FirstFrame_String3: TString4096 | None = None
    Source_Duration_FirstFrame_String4: TString4096 | None = None
    Source_Duration_FirstFrame_String5: TString4096 | None = None
    Source_Duration_FirstFrame_String: TString4096 | None = None
    Source_Duration_LastFrame: CoerceFloat = None
    Source_Duration_LastFrame_String1: TString4096 | None = None
    Source_Duration_LastFrame_String2: TString4096 | None = None
    Source_Duration_LastFrame_String3: TString4096 | None = None
    Source_Duration_LastFrame_String4: TString4096 | None = None
    Source_Duration_LastFrame_String5: TString4096 | None = None
    Source_Duration_LastFrame_String: TString4096 | None = None
    Source_Duration: CoerceFloat = None
    Source_Duration_String1: TString4096 | None = None
    Source_Duration_String2: TString4096 | None = None
    Source_Duration_String3: TString4096 | None = None
    Source_Duration_String4: TString4096 | None = None
    Source_Duration_String5: TString4096 | None = None
    Source_Duration_String: TString4096 | None = None
    Source_FrameCount: CoerceInteger = None
    Source_SamplingCount: CoerceInteger = None
    Source_StreamSize_Encoded: CoerceInteger = None
    Source_StreamSize_Encoded_Proportion: TString4096 | None = None
    Source_StreamSize_Encoded_String1: TString4096 | None = None
    Source_StreamSize_Encoded_String2: TString4096 | None = None
    Source_StreamSize_Encoded_String3: TString4096 | None = None
    Source_StreamSize_Encoded_String4: TString4096 | None = None
    Source_StreamSize_Encoded_String5: TString4096 | None = None
    Source_StreamSize_Encoded_String: TString4096 | None = None
    Source_StreamSize: CoerceInteger = None
    Source_StreamSize_Proportion: TString4096 | None = None
    Source_StreamSize_String1: TString4096 | None = None
    Source_StreamSize_String2: TString4096 | None = None
    Source_StreamSize_String3: TString4096 | None = None
    Source_StreamSize_String4: TString4096 | None = None
    Source_StreamSize_String5: TString4096 | None = None
    Source_StreamSize_String: TString4096 | None = None
    Standard: TString4096 | None = None
    Status: CoerceInteger = None
    Stored_Height: CoerceInteger = None
    Stored_Width: CoerceInteger = None
    StreamCount: CoerceInteger = None
    StreamKindID: CoerceInteger = None
    StreamKind: TString4096 | None = None
    StreamKindPos: CoerceInteger = None
    StreamKind_String: TString4096 | None = None
    StreamOrder: TString4096 | None = None
    StreamSize_Demuxed: CoerceInteger = None
    StreamSize_Demuxed_String1: TString4096 | None = None
    StreamSize_Demuxed_String2: TString4096 | None = None
    StreamSize_Demuxed_String3: TString4096 | None = None
    StreamSize_Demuxed_String4: TString4096 | None = None
    StreamSize_Demuxed_String5: TString4096 | None = None
    StreamSize_Demuxed_String: TString4096 | None = None
    StreamSize_Encoded: CoerceInteger = None
    StreamSize_Encoded_Proportion: TString4096 | None = None
    StreamSize_Encoded_String1: TString4096 | None = None
    StreamSize_Encoded_String2: TString4096 | None = None
    StreamSize_Encoded_String3: TString4096 | None = None
    StreamSize_Encoded_String4: TString4096 | None = None
    StreamSize_Encoded_String5: TString4096 | None = None
    StreamSize_Encoded_String: TString4096 | None = None
    StreamSize: CoerceInteger = None
    StreamSize_Proportion: TString4096 | None = None
    StreamSize_String1: TString4096 | None = None
    StreamSize_String2: TString4096 | None = None
    StreamSize_String3: TString4096 | None = None
    StreamSize_String4: TString4096 | None = None
    StreamSize_String5: TString4096 | None = None
    StreamSize_String: TString4096 | None = None
    Subject: TString4096 | None = None
    SubTrack: TString4096 | None = None
    Summary: TString4096 | None = None
    Synopsis: TString4096 | None = None
    Tagged_Application: TString4096 | None = None
    Tagged_Date: TString4096 | datetime.datetime | None = None
    TermsOfUse: TString4096 | None = None
    Text_Codec_List: TString4096 | None = None
    TextCount: CoerceInteger = None
    Text_Format_List: TString4096 | None = None
    Text_Format_WithHint_List: TString4096 | None = None
    Text_Language_List: TString4096 | None = None
    ThanksTo: TString4096 | None = None
    TimeCode_DropFrame: TString4096 | None = None
    TimeCode_FirstFrame: TString4096 | None = None
    TimeCode_LastFrame: TString4096 | None = None
    TimeCode_MaxFrameNumber: TString4096 | None = None
    TimeCode_MaxFrameNumber_Theory: TString4096 | None = None
    TimeCode_Settings: TString4096 | None = None
    TimeCode_Source: TString4096 | None = None
    TimeCode_Striped: TString4096 | None = None
    TimeCode_Striped_String: TString4096 | None = None
    TimeCode_Stripped: TString4096 | None = None
    TimeCode_Stripped_String: TString4096 | None = None
    TimeStamp_FirstFrame: CoerceFloat = None
    TimeStamp_FirstFrame_String1: TString4096 | None = None
    TimeStamp_FirstFrame_String2: TString4096 | None = None
    TimeStamp_FirstFrame_String3: TString4096 | None = None
    TimeStamp_FirstFrame_String4: TString4096 | None = None
    TimeStamp_FirstFrame_String5: TString4096 | None = None
    TimeStamp_FirstFrame_String: TString4096 | None = None
    TimeZone: TString4096 | None = None
    TimeZones: TString4096 | None = None
    Title: TString4096 | None = None
    Title_More: TString4096 | None = None
    Title_Url: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Track: TString4096 | None = None
    Track_More: TString4096 | None = None
    Track_Position: CoerceInteger = None
    Track_Position_Total: CoerceInteger = None
    Track_Sort: TString4096 | None = None
    Track_Url: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    transfer_characteristics: TString4096 | None = None
    transfer_characteristics_Original: TString4096 | None = None
    transfer_characteristics_Original_Source: TString4096 | None = None
    transfer_characteristics_Source: TString4096 | None = None
    Type: TString4096 | None = None
    UMID: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    UniqueID: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    UniqueID_String: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    UniversalAdID_Registry: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    UniversalAdID_String: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    UniversalAdID_Value: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Video0_Delay: CoerceInteger = None
    Video0_Delay_String1: TString4096 | None = None
    Video0_Delay_String2: TString4096 | None = None
    Video0_Delay_String3: TString4096 | None = None
    Video0_Delay_String4: TString4096 | None = None
    Video0_Delay_String5: TString4096 | None = None
    Video0_Delay_String: TString4096 | None = None
    Video_Codec_List: TString4096 | None = None
    VideoCount: CoerceInteger = None
    Video_Delay: CoerceFloat = None
    Video_Delay_String1: TString4096 | None = None
    Video_Delay_String2: TString4096 | None = None
    Video_Delay_String3: TString4096 | None = None
    Video_Delay_String4: TString4096 | None = None
    Video_Delay_String5: TString4096 | None = None
    Video_Delay_String: TString4096 | None = None
    Video_Format_List: TString4096 | None = None
    Video_Format_WithHint_List: TString4096 | None = None
    Video_Language_List: TString4096 | None = None
    Width_CleanAperture: CoerceInteger = None
    Width_CleanAperture_String: TString4096 | None = None
    Width: CoerceInteger = None
    Width_Offset: CoerceInteger = None
    Width_Offset_String: TString4096 | None = None
    Width_Original: CoerceInteger = None
    Width_Original_String: TString4096 | None = None
    Width_String: TString4096 | None = None
    WrittenBy: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    Written_Date: TString4096 | datetime.datetime | None = None
    Written_Location: TString4096 | None = Field(default=None, json_schema_extra={"pii_risk": True})
    extra: MediaInfoTrackExtra | None = Field(default=None, json_schema_extra={"pii_risk": True})


class MediaInfoVersion(BaseModel):
    name: Literal["MediaInfoLib"]
    version: float = Field(ge=18.08)
    url: Literal["https://mediaarea.net/MediaInfo"]


class MediaInfoValidationModel(MediaInfoTrack):
    """Validation model for MediaInfoAnnotationModel."""

    Audio: list[MediaInfoTrack] | None = None
    Image: list[MediaInfoTrack] | None = None
    Menu: list[MediaInfoTrack] | None = None
    Other: list[MediaInfoTrack] | None = None
    Text: list[MediaInfoTrack] | None = None
    Video: list[MediaInfoTrack] | None = None
    creatingLibrary: MediaInfoVersion | None = None

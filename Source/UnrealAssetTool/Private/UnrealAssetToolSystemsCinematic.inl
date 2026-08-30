static bool IsMovieSceneChannelStruct(const UScriptStruct* Struct)
{
    if (!Struct)
    {
        return false;
    }
    const FString Name = Struct->GetName();
    return Name.Contains(TEXT("MovieScene")) && Name.EndsWith(TEXT("Channel"));
}

static int32 CountArrayField(UScriptStruct* Struct, const void* Value, const FName Name)
{
    return GetArrayCount(Struct, Value, Name);
}

static bool ScanMovieSceneChannelsRecursive(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& SequencePath,
    const FString& SectionPath,
    const FString& PropertyPath,
    UObject* Owner,
    int32 Depth,
    int32& ChannelIndex,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Property || !ValuePtr || Depth > MaxReferenceDepth || ChannelIndex >= MaxStructuredRowsPerAsset)
    {
        return true;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        UScriptStruct* Struct = StructProperty->Struct;
        if (!Struct)
        {
            return true;
        }

        if (IsMovieSceneChannelStruct(Struct))
        {
            bool bTruncated = false;
            const FString Raw = ExportProperty(Property, ValuePtr, Owner, bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("sequence_path"), SequencePath);
            Row->SetStringField(TEXT("section_path"), SectionPath);
            Row->SetNumberField(TEXT("channel_index"), ChannelIndex++);
            Row->SetStringField(TEXT("property_path"), PropertyPath);
            Row->SetStringField(TEXT("channel_type"), Struct->GetPathName());
            Row->SetNumberField(TEXT("key_count"), CountArrayField(Struct, ValuePtr, TEXT("Times")));
            Row->SetNumberField(TEXT("value_count"), CountArrayField(Struct, ValuePtr, TEXT("Values")));
            Row->SetStringField(TEXT("default_value"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("DefaultValue"), TEXT("Default") }));
            Row->SetStringField(TEXT("raw_value"), Raw);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.MovieSceneChannels.Write(Row))
            {
                return false;
            }
            ++Counts.MovieSceneChannels;
            return true;
        }

        for (TFieldIterator<FProperty> It(Struct); It; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner))
            {
                continue;
            }
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const FString Child = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                if (!ScanMovieSceneChannelsRecursive(
                    Inner, InnerValue, SequencePath, SectionPath, Child,
                    Owner, Depth + 1, ChannelIndex, Writers, Counts))
                {
                    return false;
                }
            }
        }
        return true;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        const int32 Limit = FMath::Min(Helper.Num(), 4096);
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            if (!ScanMovieSceneChannelsRecursive(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                SequencePath,
                SectionPath,
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Owner,
                Depth + 1,
                ChannelIndex,
                Writers,
                Counts))
            {
                return false;
            }
        }
    }
    return true;
}

static bool ScanSectionChannels(
    UObject* Section,
    const FString& SequencePath,
    int32& OutChannelCount,
    FWriters& Writers,
    FCounts& Counts)
{
    OutChannelCount = 0;
    if (!Section)
    {
        return true;
    }
    TSet<FString> SeenRoots;
    for (UClass* Class = Section->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }
            const FString Key = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (SeenRoots.Contains(Key))
            {
                continue;
            }
            SeenRoots.Add(Key);
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Section, StaticIndex);
                const FString Path = Property->GetName() +
                    (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                if (!ScanMovieSceneChannelsRecursive(
                    Property, ValuePtr, SequencePath, Section->GetPathName(), Path,
                    Section, 0, OutChannelCount, Writers, Counts))
                {
                    return false;
                }
            }
        }
    }
    return true;
}

static bool EmitMovieSceneBindingArray(
    UObject* MovieScene,
    const FString& SequencePath,
    const FName PropertyName,
    const FString& BindingKind,
    int32& InOutBindingIndex,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!MovieScene)
    {
        return true;
    }
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(MovieScene->GetClass()->FindPropertyByName(PropertyName));
    if (!ArrayProperty)
    {
        return true;
    }
    const FStructProperty* StructProperty = CastField<FStructProperty>(ArrayProperty->Inner);
    if (!StructProperty || !StructProperty->Struct)
    {
        return true;
    }
    const void* ValuePtr = ArrayProperty->ContainerPtrToValuePtr<void>(MovieScene);
    if (!ValuePtr)
    {
        return true;
    }

    FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
    const int32 Limit = FMath::Min(Helper.Num(), MaxStructuredRowsPerAsset);
    for (int32 Index = 0; Index < Limit; ++Index)
    {
        const void* Item = Helper.GetRawPtr(Index);
        UScriptStruct* Struct = StructProperty->Struct;
        bool bTruncated = false;
        const FString Raw = ExportProperty(StructProperty, Item, MovieScene, bTruncated);
        UObject* TemplateObject = GetFirstObjectField(Struct, Item, {TEXT("ObjectTemplate"), TEXT("Template")});
        UObject* PossessedClass = GetFirstObjectField(Struct, Item, {TEXT("PossessedObjectClass"), TEXT("ObjectClass")});

        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("sequence_path"), SequencePath);
        Row->SetNumberField(TEXT("binding_index"), InOutBindingIndex++);
        Row->SetStringField(TEXT("binding_kind"), BindingKind);
        Row->SetNumberField(TEXT("source_index"), Index);
        Row->SetStringField(TEXT("source_property"), PropertyName.ToString());
        Row->SetStringField(TEXT("struct_type"), Struct->GetPathName());
        Row->SetStringField(TEXT("guid"), ExportFirstField(Struct, Item, MovieScene, {TEXT("ObjectGuid"), TEXT("Guid"), TEXT("ID")}));
        Row->SetStringField(TEXT("name"), ExportFirstField(Struct, Item, MovieScene, {TEXT("BindingName"), TEXT("Name")}));
        Row->SetStringField(TEXT("parent_guid"), ExportFirstField(Struct, Item, MovieScene, {TEXT("ParentGuid"), TEXT("Parent")}));
        Row->SetStringField(TEXT("object_template_path"), TemplateObject ? TemplateObject->GetPathName() : FString());
        Row->SetStringField(TEXT("object_template_class"), TemplateObject ? TemplateObject->GetClass()->GetPathName() : FString());
        Row->SetStringField(TEXT("possessed_object_class"), PossessedClass ? PossessedClass->GetPathName() : FString());
        Row->SetNumberField(TEXT("track_count"), GetArrayCount(Struct, Item, TEXT("Tracks")));
        Row->SetStringField(TEXT("raw_value"), Raw);
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!Writers.MovieSceneBindings.Write(Row))
        {
            return false;
        }
        ++Counts.MovieSceneBindings;
    }
    return true;
}

static bool ScanLevelSequence(
    UObject* Sequence,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Sequence)
    {
        return true;
    }
    const FString SequencePath = Asset.GetSoftObjectPath().ToString();
    UObject* MovieScene = GetFirstObjectField(Sequence, {TEXT("MovieScene")});
    if (MovieScene && !WriteObjectState(MovieScene, SequencePath, TEXT("movie_scene"), Writers, Counts, SeenStateOwners))
    {
        return false;
    }

    int32 BindingCount = 0;
    if (MovieScene)
    {
        if (!EmitMovieSceneBindingArray(MovieScene, SequencePath, TEXT("ObjectBindings"), TEXT("object_binding"), BindingCount, Writers, Counts)) return false;
        if (!EmitMovieSceneBindingArray(MovieScene, SequencePath, TEXT("Bindings"), TEXT("object_binding"), BindingCount, Writers, Counts)) return false;
        if (!EmitMovieSceneBindingArray(MovieScene, SequencePath, TEXT("Possessables"), TEXT("possessable"), BindingCount, Writers, Counts)) return false;
        if (!EmitMovieSceneBindingArray(MovieScene, SequencePath, TEXT("Spawnables"), TEXT("spawnable"), BindingCount, Writers, Counts)) return false;
    }

    TArray<UObject*> Nested;
    if (MovieScene)
    {
        GatherNestedObjects(MovieScene, Nested);
    }

    int32 TrackCount = 0;
    int32 SectionCount = 0;
    int32 SequenceChannelCount = 0;
    for (UObject* Object : Nested)
    {
        if (!Object)
        {
            continue;
        }
        if (ClassInheritsName(Object->GetClass(), TEXT("MovieSceneTrack")))
        {
            int32 DirectSectionCount = 0;
            for (UObject* Child : Nested)
            {
                if (Child && Child->GetOuter() == Object && ClassInheritsName(Child->GetClass(), TEXT("MovieSceneSection")))
                {
                    ++DirectSectionCount;
                }
            }

            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("sequence_path"), SequencePath);
            Row->SetNumberField(TEXT("track_index"), TrackCount++);
            Row->SetStringField(TEXT("track_path"), Object->GetPathName());
            Row->SetStringField(TEXT("track_class"), Object->GetClass()->GetPathName());
            Row->SetStringField(TEXT("track_name"), Object->GetName());
            Row->SetStringField(TEXT("outer_path"), Object->GetOuter() ? Object->GetOuter()->GetPathName() : FString());
            Row->SetStringField(TEXT("binding_guid"), ExportFirstField(Object, {TEXT("ObjectBindingID"), TEXT("ObjectBindingGuid"), TEXT("BindingID")}));
            Row->SetNumberField(TEXT("section_count"), DirectSectionCount);
            Row->SetStringField(TEXT("display_name"), ExportFirstField(Object, {TEXT("DisplayName"), TEXT("TrackRowDisplayName")}));
            if (!Writers.MovieSceneTracks.Write(Row))
            {
                return false;
            }
            ++Counts.MovieSceneTracks;
            if (!WriteObjectState(Object, SequencePath, TEXT("movie_scene_track"), Writers, Counts, SeenStateOwners))
            {
                return false;
            }
        }
    }

    for (UObject* Object : Nested)
    {
        if (!Object || !ClassInheritsName(Object->GetClass(), TEXT("MovieSceneSection")))
        {
            continue;
        }
        UObject* Track = FindNearestOuterByClassName(Object, TEXT("MovieSceneTrack"));
        int32 ChannelCount = 0;
        if (!ScanSectionChannels(Object, SequencePath, ChannelCount, Writers, Counts))
        {
            return false;
        }
        SequenceChannelCount += ChannelCount;

        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("sequence_path"), SequencePath);
        Row->SetNumberField(TEXT("section_index"), SectionCount++);
        Row->SetStringField(TEXT("section_path"), Object->GetPathName());
        Row->SetStringField(TEXT("section_class"), Object->GetClass()->GetPathName());
        Row->SetStringField(TEXT("section_name"), Object->GetName());
        Row->SetStringField(TEXT("track_path"), Track ? Track->GetPathName() : FString());
        Row->SetStringField(TEXT("range"), ExportFirstField(Object, {TEXT("SectionRange"), TEXT("Range")}));
        Row->SetStringField(TEXT("row_index"), ExportField(Object, TEXT("RowIndex")));
        Row->SetStringField(TEXT("overlap_priority"), ExportField(Object, TEXT("OverlapPriority")));
        Row->SetStringField(TEXT("pre_roll_frames"), ExportFirstField(Object, {TEXT("PreRollFrames"), TEXT("PreRollTime")}));
        Row->SetStringField(TEXT("post_roll_frames"), ExportFirstField(Object, {TEXT("PostRollFrames"), TEXT("PostRollTime")}));
        Row->SetStringField(TEXT("active"), ExportFirstField(Object, {TEXT("bIsActive"), TEXT("bActive")}));
        Row->SetStringField(TEXT("locked"), ExportFirstField(Object, {TEXT("bIsLocked"), TEXT("bLocked")}));
        Row->SetNumberField(TEXT("channel_count"), ChannelCount);
        if (!Writers.MovieSceneSections.Write(Row))
        {
            return false;
        }
        ++Counts.MovieSceneSections;
        if (!WriteObjectState(Object, SequencePath, TEXT("movie_scene_section"), Writers, Counts, SeenStateOwners))
        {
            return false;
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("sequence_path"), SequencePath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("class_path"), Sequence->GetClass()->GetPathName());
    Row->SetStringField(TEXT("movie_scene_path"), MovieScene ? MovieScene->GetPathName() : FString());
    Row->SetNumberField(TEXT("binding_count"), BindingCount);
    Row->SetNumberField(TEXT("track_count"), TrackCount);
    Row->SetNumberField(TEXT("section_count"), SectionCount);
    Row->SetNumberField(TEXT("channel_count"), SequenceChannelCount);
    Row->SetStringField(TEXT("display_rate"), MovieScene ? ExportFirstField(MovieScene, {TEXT("DisplayRate")}) : FString());
    Row->SetStringField(TEXT("tick_resolution"), MovieScene ? ExportFirstField(MovieScene, {TEXT("TickResolution")}) : FString());
    Row->SetStringField(TEXT("playback_range"), MovieScene ? ExportFirstField(MovieScene, {TEXT("PlaybackRange")}) : FString());
    if (!Writers.LevelSequences.Write(Row))
    {
        return false;
    }
    ++Counts.LevelSequences;
    return true;
}

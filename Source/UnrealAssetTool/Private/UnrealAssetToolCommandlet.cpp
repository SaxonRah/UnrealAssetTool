#include "UnrealAssetToolCommandlet.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Dom/JsonObject.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraph/EdGraphSchema.h"
#include "Engine/Blueprint.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace UnrealAssetTool
{
    static constexpr int32 SchemaVersion = 1;
    static constexpr int32 SourceChunkLines = 200;

    class FJsonlWriter
    {
    public:
        explicit FJsonlWriter(const FString& Filename)
        {
            Archive.Reset(IFileManager::Get().CreateFileWriter(*Filename));
        }

        bool IsValid() const
        {
            return Archive.IsValid();
        }

        bool Write(const TSharedRef<FJsonObject>& Object)
        {
            if (!Archive)
            {
                return false;
            }

            FString Line;
            const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
                TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);

            if (!FJsonSerializer::Serialize(Object, Writer))
            {
                return false;
            }

            Line.AppendChar(TEXT('\n'));
            FTCHARToUTF8 Utf8(*Line);
            Archive->Serialize(const_cast<ANSICHAR*>(Utf8.Get()), Utf8.Length());
            return !Archive->IsError();
        }

    private:
        TUniquePtr<FArchive> Archive;
    };

    struct FScanCounts
    {
        int64 Files = 0;
        int64 SourceChunks = 0;
        int64 Assets = 0;
        int64 AssetDependencies = 0;
        int64 Blueprints = 0;
        int64 BlueprintGraphs = 0;
        int64 BlueprintNodes = 0;
        int64 BlueprintEdges = 0;
        int64 BlueprintVariables = 0;
        int64 BlueprintComponents = 0;
    };

    static FString NormalizeAbsolutePath(const FString& InPath)
    {
        FString Path = FPaths::ConvertRelativePathToFull(InPath);
        FPaths::NormalizeFilename(Path);
        FPaths::CollapseRelativeDirectories(Path);
        return Path;
    }

    static bool IsInsideDirectory(const FString& File, const FString& Directory)
    {
        FString NormalizedFile = NormalizeAbsolutePath(File);
        FString NormalizedDirectory = NormalizeAbsolutePath(Directory);
        if (!NormalizedDirectory.EndsWith(TEXT("/")))
        {
            NormalizedDirectory.AppendChar(TEXT('/'));
        }
        return NormalizedFile.StartsWith(NormalizedDirectory, ESearchCase::IgnoreCase);
    }

    static bool IsGeneratedPath(const FString& RelativePath)
    {
        FString P = RelativePath;
        FPaths::NormalizeFilename(P);
        P = TEXT("/") + P.ToLower() + TEXT("/");

        static const TCHAR* Excluded[] =
        {
            TEXT("/.git/"),
            TEXT("/.vs/"),
            TEXT("/.idea/"),
            TEXT("/.uatool/"),
            TEXT("/binaries/"),
            TEXT("/deriveddatacache/"),
            TEXT("/intermediate/"),
            TEXT("/saved/")
        };

        for (const TCHAR* Segment : Excluded)
        {
            if (P.Contains(Segment, ESearchCase::IgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

    static FString FileKind(const FString& RelativePath)
    {
        const FString Lower = RelativePath.ToLower();
        const FString Ext = FPaths::GetExtension(RelativePath, true).ToLower();

        if (Ext == TEXT(".uasset")) return TEXT("unreal_asset");
        if (Ext == TEXT(".umap")) return TEXT("unreal_map");
        if (Lower.EndsWith(TEXT(".build.cs"))) return TEXT("unreal_build_rules");
        if (Lower.EndsWith(TEXT(".target.cs"))) return TEXT("unreal_target_rules");
        if (Ext == TEXT(".uproject")) return TEXT("unreal_project");
        if (Ext == TEXT(".uplugin")) return TEXT("unreal_plugin");
        if (Ext == TEXT(".ini")) return TEXT("config");
        if (Ext == TEXT(".cpp") || Ext == TEXT(".cc") || Ext == TEXT(".cxx") || Ext == TEXT(".c")) return TEXT("source");
        if (Ext == TEXT(".h") || Ext == TEXT(".hpp") || Ext == TEXT(".inl")) return TEXT("header");
        if (Ext == TEXT(".usf") || Ext == TEXT(".ush")) return TEXT("shader_source");
        if (Ext == TEXT(".py")) return TEXT("python");
        if (Ext == TEXT(".cs")) return TEXT("csharp");
        if (Ext == TEXT(".json")) return TEXT("json");
        if (Ext == TEXT(".xml")) return TEXT("xml");
        if (Ext == TEXT(".md") || Ext == TEXT(".txt")) return TEXT("documentation");
        return TEXT("file");
    }

    static bool IsTextFile(const FString& RelativePath)
    {
        const FString Kind = FileKind(RelativePath);
        return Kind == TEXT("source") ||
               Kind == TEXT("header") ||
               Kind == TEXT("shader_source") ||
               Kind == TEXT("python") ||
               Kind == TEXT("csharp") ||
               Kind == TEXT("json") ||
               Kind == TEXT("xml") ||
               Kind == TEXT("documentation") ||
               Kind == TEXT("config") ||
               Kind == TEXT("unreal_project") ||
               Kind == TEXT("unreal_plugin") ||
               Kind == TEXT("unreal_build_rules") ||
               Kind == TEXT("unreal_target_rules");
    }

    static TSharedRef<FJsonObject> PinTypeToJson(const FEdGraphPinType& PinType)
    {
        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("category"), PinType.PinCategory.ToString());
        Json->SetStringField(TEXT("subcategory"), PinType.PinSubCategory.ToString());
        Json->SetNumberField(TEXT("container_type"), static_cast<int32>(PinType.ContainerType));
        Json->SetBoolField(TEXT("is_reference"), PinType.bIsReference);
        Json->SetBoolField(TEXT("is_const"), PinType.bIsConst);

        if (UObject* SubCategoryObject = PinType.PinSubCategoryObject.Get())
        {
            Json->SetStringField(TEXT("subcategory_object"), SubCategoryObject->GetPathName());
        }
        else
        {
            Json->SetStringField(TEXT("subcategory_object"), TEXT(""));
        }
        return Json;
    }

    static FString GraphKind(const UBlueprint* Blueprint, const UEdGraph* Graph)
    {
        if (Blueprint->UbergraphPages.Contains(Graph)) return TEXT("ubergraph");
        if (Blueprint->FunctionGraphs.Contains(Graph)) return TEXT("function");
        if (Blueprint->MacroGraphs.Contains(Graph)) return TEXT("macro");
        if (Blueprint->DelegateSignatureGraphs.Contains(Graph)) return TEXT("delegate_signature");
        if (Blueprint->EventGraphs.Contains(Graph)) return TEXT("event_graph_generated");
        if (Blueprint->IntermediateGeneratedGraphs.Contains(Graph)) return TEXT("intermediate_generated");
        return TEXT("graph");
    }

    static FString MakeNodeId(const FString& BlueprintPath, const UEdGraph* Graph, const UEdGraphNode* Node, int32 FallbackIndex)
    {
        FString Guid = Node->NodeGuid.ToString(EGuidFormats::DigitsWithHyphensLower);
        if (!Node->NodeGuid.IsValid())
        {
            Guid = FString::Printf(TEXT("index-%d"), FallbackIndex);
        }
        return FString::Printf(TEXT("%s::%s::%s"), *BlueprintPath, *Graph->GetName(), *Guid);
    }

    static FString MakePinId(const FString& NodeId, const UEdGraphPin* Pin, int32 FallbackIndex)
    {
        FString Guid = Pin->PinId.ToString(EGuidFormats::DigitsWithHyphensLower);
        if (!Pin->PinId.IsValid())
        {
            Guid = FString::Printf(TEXT("pin-%d"), FallbackIndex);
        }
        return FString::Printf(TEXT("%s::%s"), *NodeId, *Guid);
    }

    static bool SaveJsonObject(const FString& Filename, const TSharedRef<FJsonObject>& Object)
    {
        FString JsonText;
        const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&JsonText);
        if (!FJsonSerializer::Serialize(Object, Writer))
        {
            return false;
        }
        return FFileHelper::SaveStringToFile(JsonText, *Filename, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    }

    static bool ScanFiles(
        const FString& ProjectDir,
        const FString& ToolPluginDir,
        const FString& OutputDir,
        bool bIncludeGenerated,
        bool bIncludeSelf,
        FJsonlWriter& FilesWriter,
        FJsonlWriter& SourceWriter,
        FScanCounts& Counts)
    {
        TArray<FString> Files;
        IFileManager::Get().FindFilesRecursive(Files, *ProjectDir, TEXT("*"), true, false, false);
        Files.Sort();

        for (const FString& FullPathUnnormalized : Files)
        {
            const FString FullPath = NormalizeAbsolutePath(FullPathUnnormalized);
            FString RelativePath = FullPath;
            FPaths::MakePathRelativeTo(RelativePath, *ProjectDir);
            FPaths::NormalizeFilename(RelativePath);

            // The index describes the target project, not UnrealAssetTool itself.
            // Keep this separate from IncludeGenerated so generated/cache data can
            // be requested without also polluting the index with the scanner.
            if (!bIncludeSelf && !ToolPluginDir.IsEmpty() && IsInsideDirectory(FullPath, ToolPluginDir))
            {
                continue;
            }

            // Never index the output currently being produced, even when a custom
            // output directory name is used and IncludeGenerated is enabled.
            if (IsInsideDirectory(FullPath, OutputDir))
            {
                continue;
            }

            if (!bIncludeGenerated && IsGeneratedPath(RelativePath))
            {
                continue;
            }

            const int64 Size = IFileManager::Get().FileSize(*FullPath);
            const FDateTime Modified = IFileManager::Get().GetTimeStamp(*FullPath);

            const TSharedRef<FJsonObject> FileJson = MakeShared<FJsonObject>();
            FileJson->SetStringField(TEXT("path"), RelativePath);
            FileJson->SetStringField(TEXT("kind"), FileKind(RelativePath));
            FileJson->SetStringField(TEXT("extension"), FPaths::GetExtension(RelativePath, true).ToLower());
            FileJson->SetNumberField(TEXT("size"), static_cast<double>(Size));
            FileJson->SetStringField(TEXT("modified_utc"), Modified.ToIso8601());
            if (!FilesWriter.Write(FileJson))
            {
                return false;
            }
            ++Counts.Files;

            if (!IsTextFile(RelativePath))
            {
                continue;
            }

            FString Text;
            if (!FFileHelper::LoadFileToString(Text, *FullPath))
            {
                continue;
            }

            TArray<FString> Lines;
            Text.ParseIntoArrayLines(Lines, false);
            if (Lines.IsEmpty() && !Text.IsEmpty())
            {
                Lines.Add(Text);
            }

            for (int32 Start = 0; Start < Lines.Num(); Start += SourceChunkLines)
            {
                const int32 EndExclusive = FMath::Min(Start + SourceChunkLines, Lines.Num());
                FString Chunk;
                for (int32 LineIndex = Start; LineIndex < EndExclusive; ++LineIndex)
                {
                    if (!Chunk.IsEmpty())
                    {
                        Chunk.AppendChar(TEXT('\n'));
                    }
                    Chunk.Append(Lines[LineIndex]);
                }

                const TSharedRef<FJsonObject> ChunkJson = MakeShared<FJsonObject>();
                ChunkJson->SetStringField(TEXT("path"), RelativePath);
                ChunkJson->SetNumberField(TEXT("start_line"), Start + 1);
                ChunkJson->SetNumberField(TEXT("end_line"), EndExclusive);
                ChunkJson->SetStringField(TEXT("text"), Chunk);
                if (!SourceWriter.Write(ChunkJson))
                {
                    return false;
                }
                ++Counts.SourceChunks;
            }
        }
        return true;
    }

    static bool ScanBlueprint(
        UBlueprint* Blueprint,
        const FString& ObjectPath,
        FJsonlWriter& BlueprintsWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& EdgesWriter,
        FScanCounts& Counts)
    {
        const TSharedRef<FJsonObject> BlueprintJson = MakeShared<FJsonObject>();
        BlueprintJson->SetStringField(TEXT("object_path"), ObjectPath);
        BlueprintJson->SetStringField(TEXT("name"), Blueprint->GetName());
        BlueprintJson->SetStringField(TEXT("class"), Blueprint->GetClass()->GetPathName());
        BlueprintJson->SetStringField(TEXT("parent_class"), Blueprint->ParentClass ? Blueprint->ParentClass->GetPathName() : TEXT(""));
        BlueprintJson->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass ? Blueprint->GeneratedClass->GetPathName() : TEXT(""));
        BlueprintJson->SetNumberField(TEXT("blueprint_type"), static_cast<int32>(Blueprint->BlueprintType));
        BlueprintJson->SetNumberField(TEXT("status"), static_cast<int32>(Blueprint->Status));

        TArray<TSharedPtr<FJsonValue>> VariablesJson;
        for (const FBPVariableDescription& Variable : Blueprint->NewVariables)
        {
            const TSharedRef<FJsonObject> VariableJson = MakeShared<FJsonObject>();
            VariableJson->SetStringField(TEXT("name"), Variable.VarName.ToString());
            VariableJson->SetStringField(TEXT("guid"), Variable.VarGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
            VariableJson->SetStringField(TEXT("category"), Variable.Category.ToString());
            VariableJson->SetStringField(TEXT("default_value"), Variable.DefaultValue);
            VariableJson->SetNumberField(TEXT("property_flags"), static_cast<double>(Variable.PropertyFlags));
            VariableJson->SetObjectField(TEXT("type"), PinTypeToJson(Variable.VarType));
            VariablesJson.Add(MakeShared<FJsonValueObject>(VariableJson));
            ++Counts.BlueprintVariables;
        }
        BlueprintJson->SetArrayField(TEXT("variables"), VariablesJson);

        TArray<TSharedPtr<FJsonValue>> ComponentsJson;
        if (Blueprint->SimpleConstructionScript)
        {
            for (USCS_Node* SCSNode : Blueprint->SimpleConstructionScript->GetAllNodes())
            {
                if (!SCSNode)
                {
                    continue;
                }
                const TSharedRef<FJsonObject> ComponentJson = MakeShared<FJsonObject>();
                ComponentJson->SetStringField(TEXT("variable_name"), SCSNode->GetVariableName().ToString());
                ComponentJson->SetStringField(TEXT("component_class"), SCSNode->ComponentClass ? SCSNode->ComponentClass->GetPathName() : TEXT(""));
                ComponentJson->SetStringField(TEXT("template"), SCSNode->ComponentTemplate ? SCSNode->ComponentTemplate->GetPathName() : TEXT(""));
                ComponentJson->SetStringField(TEXT("parent_component_or_variable"), SCSNode->ParentComponentOrVariableName.ToString());
                ComponentJson->SetStringField(TEXT("parent_owner_class"), SCSNode->ParentComponentOwnerClassName.ToString());
                ComponentJson->SetStringField(TEXT("attach_to"), SCSNode->AttachToName.ToString());
                ComponentJson->SetStringField(TEXT("guid"), SCSNode->VariableGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
                ComponentJson->SetBoolField(TEXT("is_root"), SCSNode->IsRootNode());
                ComponentsJson.Add(MakeShared<FJsonValueObject>(ComponentJson));
                ++Counts.BlueprintComponents;
            }
        }
        BlueprintJson->SetArrayField(TEXT("components"), ComponentsJson);

        TArray<UEdGraph*> Graphs;
        Blueprint->GetAllGraphs(Graphs);
        BlueprintJson->SetNumberField(TEXT("graph_count"), Graphs.Num());

        if (!BlueprintsWriter.Write(BlueprintJson))
        {
            return false;
        }
        ++Counts.Blueprints;

        for (UEdGraph* Graph : Graphs)
        {
            if (!Graph)
            {
                continue;
            }
            ++Counts.BlueprintGraphs;

            TMap<const UEdGraphNode*, FString> NodeIds;
            TMap<const UEdGraphPin*, FString> PinIds;

            for (int32 NodeIndex = 0; NodeIndex < Graph->Nodes.Num(); ++NodeIndex)
            {
                UEdGraphNode* Node = Graph->Nodes[NodeIndex];
                if (!Node)
                {
                    continue;
                }

                const FString NodeId = MakeNodeId(ObjectPath, Graph, Node, NodeIndex);
                NodeIds.Add(Node, NodeId);

                const TSharedRef<FJsonObject> NodeJson = MakeShared<FJsonObject>();
                NodeJson->SetStringField(TEXT("node_id"), NodeId);
                NodeJson->SetStringField(TEXT("blueprint_path"), ObjectPath);
                NodeJson->SetStringField(TEXT("graph_name"), Graph->GetName());
                NodeJson->SetStringField(TEXT("graph_kind"), GraphKind(Blueprint, Graph));
                NodeJson->SetStringField(TEXT("graph_class"), Graph->GetClass()->GetPathName());
                NodeJson->SetStringField(TEXT("schema_class"), Graph->GetSchema() ? Graph->GetSchema()->GetClass()->GetPathName() : TEXT(""));
                NodeJson->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
                NodeJson->SetStringField(TEXT("title"), Node->GetNodeTitle(ENodeTitleType::FullTitle).ToString());
                NodeJson->SetStringField(TEXT("comment"), Node->NodeComment);
                NodeJson->SetNumberField(TEXT("x"), Node->NodePosX);
                NodeJson->SetNumberField(TEXT("y"), Node->NodePosY);

                TArray<TSharedPtr<FJsonValue>> PinsJson;
                for (int32 PinIndex = 0; PinIndex < Node->Pins.Num(); ++PinIndex)
                {
                    UEdGraphPin* Pin = Node->Pins[PinIndex];
                    if (!Pin)
                    {
                        continue;
                    }
                    const FString PinId = MakePinId(NodeId, Pin, PinIndex);
                    PinIds.Add(Pin, PinId);

                    const TSharedRef<FJsonObject> PinJson = MakeShared<FJsonObject>();
                    PinJson->SetStringField(TEXT("pin_id"), PinId);
                    PinJson->SetStringField(TEXT("name"), Pin->PinName.ToString());
                    PinJson->SetStringField(TEXT("direction"), Pin->Direction == EGPD_Input ? TEXT("input") : TEXT("output"));
                    PinJson->SetObjectField(TEXT("type"), PinTypeToJson(Pin->PinType));
                    PinJson->SetStringField(TEXT("default_value"), Pin->DefaultValue);
                    PinJson->SetStringField(TEXT("default_object"), Pin->DefaultObject ? Pin->DefaultObject->GetPathName() : TEXT(""));
                    PinJson->SetStringField(TEXT("default_text"), Pin->DefaultTextValue.ToString());
                    PinJson->SetBoolField(TEXT("hidden"), Pin->bHidden);
                    PinJson->SetBoolField(TEXT("not_connectable"), Pin->bNotConnectable);
                    PinsJson.Add(MakeShared<FJsonValueObject>(PinJson));
                }
                NodeJson->SetArrayField(TEXT("pins"), PinsJson);

                if (!NodesWriter.Write(NodeJson))
                {
                    return false;
                }
                ++Counts.BlueprintNodes;
            }

            for (UEdGraphNode* Node : Graph->Nodes)
            {
                if (!Node)
                {
                    continue;
                }
                for (UEdGraphPin* Pin : Node->Pins)
                {
                    if (!Pin || Pin->Direction != EGPD_Output)
                    {
                        continue;
                    }
                    const FString* SourcePinId = PinIds.Find(Pin);
                    if (!SourcePinId)
                    {
                        continue;
                    }

                    for (UEdGraphPin* LinkedPin : Pin->LinkedTo)
                    {
                        if (!LinkedPin)
                        {
                            continue;
                        }
                        const FString* TargetPinId = PinIds.Find(LinkedPin);
                        if (!TargetPinId)
                        {
                            continue;
                        }

                        const TSharedRef<FJsonObject> EdgeJson = MakeShared<FJsonObject>();
                        EdgeJson->SetStringField(TEXT("blueprint_path"), ObjectPath);
                        EdgeJson->SetStringField(TEXT("graph_name"), Graph->GetName());
                        EdgeJson->SetStringField(TEXT("source_pin_id"), *SourcePinId);
                        EdgeJson->SetStringField(TEXT("target_pin_id"), *TargetPinId);
                        EdgeJson->SetStringField(TEXT("pin_category"), Pin->PinType.PinCategory.ToString());
                        if (!EdgesWriter.Write(EdgeJson))
                        {
                            return false;
                        }
                        ++Counts.BlueprintEdges;
                    }
                }
            }
        }
        return true;
    }

    static bool ScanAssets(
        const FString& ProjectDir,
        const FString& ToolPluginDir,
        bool bIncludeEngine,
        bool bIncludeSelf,
        FJsonlWriter& AssetsWriter,
        FJsonlWriter& DependenciesWriter,
        FJsonlWriter& BlueprintsWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& EdgesWriter,
        FScanCounts& Counts)
    {
        FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
        IAssetRegistry& Registry = AssetRegistryModule.Get();

        TArray<FAssetData> Assets;
        Registry.GetAllAssets(Assets, true);
        Assets.Sort([](const FAssetData& A, const FAssetData& B)
        {
            return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
        });

        for (const FAssetData& Asset : Assets)
        {
            FString PackageFilename;
            const bool bHasDiskPackage = FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false);

            if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() && IsInsideDirectory(PackageFilename, ToolPluginDir))
            {
                continue;
            }

            if (!bIncludeEngine)
            {
                if (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir))
                {
                    continue;
                }
            }

            const FString ObjectPath = Asset.GetSoftObjectPath().ToString();
            const TSharedRef<FJsonObject> AssetJson = MakeShared<FJsonObject>();
            AssetJson->SetStringField(TEXT("object_path"), ObjectPath);
            AssetJson->SetStringField(TEXT("asset_name"), Asset.AssetName.ToString());
            AssetJson->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
            AssetJson->SetStringField(TEXT("package_path"), Asset.PackagePath.ToString());
            AssetJson->SetStringField(TEXT("class_path"), Asset.AssetClassPath.ToString());
            AssetJson->SetStringField(TEXT("disk_path"), bHasDiskPackage ? NormalizeAbsolutePath(PackageFilename) : TEXT(""));

            const TSharedRef<FJsonObject> TagsJson = MakeShared<FJsonObject>();
            for (const TPair<FName, FAssetTagValueRef> Tag : Asset.TagsAndValues)
            {
                TagsJson->SetStringField(Tag.Key.ToString(), Tag.Value.AsString());
            }
            AssetJson->SetObjectField(TEXT("tags"), TagsJson);

            TArray<FName> Dependencies;
            Registry.GetDependencies(
                Asset.PackageName,
                Dependencies,
                UE::AssetRegistry::EDependencyCategory::Package,
                UE::AssetRegistry::FDependencyQuery());
            Dependencies.Sort([](const FName& A, const FName& B) { return A.LexicalLess(B); });

            TArray<TSharedPtr<FJsonValue>> DependencyArray;
            for (const FName Dependency : Dependencies)
            {
                DependencyArray.Add(MakeShared<FJsonValueString>(Dependency.ToString()));

                const TSharedRef<FJsonObject> DependencyJson = MakeShared<FJsonObject>();
                DependencyJson->SetStringField(TEXT("source_package"), Asset.PackageName.ToString());
                DependencyJson->SetStringField(TEXT("target_package"), Dependency.ToString());
                DependencyJson->SetStringField(TEXT("category"), TEXT("package"));
                if (!DependenciesWriter.Write(DependencyJson))
                {
                    return false;
                }
                ++Counts.AssetDependencies;
            }
            AssetJson->SetArrayField(TEXT("dependencies"), DependencyArray);

            if (!AssetsWriter.Write(AssetJson))
            {
                return false;
            }
            ++Counts.Assets;

            if (Asset.AssetClassPath.ToString().Contains(TEXT("Blueprint"), ESearchCase::CaseSensitive))
            {
                if (UBlueprint* Blueprint = Cast<UBlueprint>(Asset.GetAsset()))
                {
                    if (!ScanBlueprint(Blueprint, ObjectPath, BlueprintsWriter, NodesWriter, EdgesWriter, Counts))
                    {
                        return false;
                    }
                }
            }
        }
        return true;
    }
}

UUnrealAssetToolCommandlet::UUnrealAssetToolCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
    UseCommandletResultAsExitCode = true;
    HelpDescription = TEXT("Indexes an Unreal project into AI-friendly JSONL records.");
    HelpUsage = TEXT("UnrealEditor-Cmd.exe Project.uproject -run=UnrealAssetTool -Output=<dir> [-IncludeGenerated] [-IncludeEngine] [-IncludeSelf]");
}

int32 UUnrealAssetToolCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetTool;

    FString OutputDir;
    FParse::Value(*Params, TEXT("Output="), OutputDir);
    const bool bIncludeGenerated = FParse::Param(*Params, TEXT("IncludeGenerated"));
    const bool bIncludeEngine = FParse::Param(*Params, TEXT("IncludeEngine"));
    const bool bIncludeSelf = FParse::Param(*Params, TEXT("IncludeSelf"));

    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty())
    {
        OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    }
    else if (FPaths::IsRelative(OutputDir))
    {
        OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    }
    OutputDir = NormalizeAbsolutePath(OutputDir);

    FString ToolPluginDir;
    const TSharedPtr<IPlugin> ToolPlugin = IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool"));
    if (ToolPlugin.IsValid())
    {
        ToolPluginDir = NormalizeAbsolutePath(ToolPlugin->GetBaseDir());
    }
    else
    {
        UE_LOG(LogTemp, Warning,
            TEXT("UnrealAssetTool: could not resolve its plugin root; self-exclusion will only affect the output directory."));
    }

    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FJsonlWriter FilesWriter(FPaths::Combine(OutputDir, TEXT("files.jsonl")));
    FJsonlWriter SourceWriter(FPaths::Combine(OutputDir, TEXT("source_chunks.jsonl")));
    FJsonlWriter AssetsWriter(FPaths::Combine(OutputDir, TEXT("assets.jsonl")));
    FJsonlWriter DependenciesWriter(FPaths::Combine(OutputDir, TEXT("asset_dependencies.jsonl")));
    FJsonlWriter BlueprintsWriter(FPaths::Combine(OutputDir, TEXT("blueprints.jsonl")));
    FJsonlWriter NodesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_nodes.jsonl")));
    FJsonlWriter EdgesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_edges.jsonl")));

    if (!FilesWriter.IsValid() || !SourceWriter.IsValid() || !AssetsWriter.IsValid() ||
        !DependenciesWriter.IsValid() || !BlueprintsWriter.IsValid() || !NodesWriter.IsValid() || !EdgesWriter.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: could not create one or more output files under %s"), *OutputDir);
        return 2;
    }

    FScanCounts Counts;
    if (!ScanFiles(ProjectDir, ToolPluginDir, OutputDir, bIncludeGenerated, bIncludeSelf, FilesWriter, SourceWriter, Counts))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: file scan failed."));
        return 3;
    }

    if (!ScanAssets(ProjectDir, ToolPluginDir, bIncludeEngine, bIncludeSelf, AssetsWriter, DependenciesWriter, BlueprintsWriter, NodesWriter, EdgesWriter, Counts))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: asset scan failed."));
        return 4;
    }

    const TSharedRef<FJsonObject> Manifest = MakeShared<FJsonObject>();
    Manifest->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Manifest->SetStringField(TEXT("tool"), TEXT("UnrealAssetTool"));
    Manifest->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Manifest->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Manifest->SetStringField(TEXT("project_file"), NormalizeAbsolutePath(FPaths::GetProjectFilePath()));
    Manifest->SetStringField(TEXT("project_dir"), ProjectDir);
    Manifest->SetStringField(TEXT("output_dir"), OutputDir);
    Manifest->SetStringField(TEXT("tool_plugin_dir"), ToolPluginDir);
    Manifest->SetBoolField(TEXT("include_generated"), bIncludeGenerated);
    Manifest->SetBoolField(TEXT("include_engine"), bIncludeEngine);
    Manifest->SetBoolField(TEXT("include_self"), bIncludeSelf);

    const TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("files"), static_cast<double>(Counts.Files));
    CountsJson->SetNumberField(TEXT("source_chunks"), static_cast<double>(Counts.SourceChunks));
    CountsJson->SetNumberField(TEXT("assets"), static_cast<double>(Counts.Assets));
    CountsJson->SetNumberField(TEXT("asset_dependencies"), static_cast<double>(Counts.AssetDependencies));
    CountsJson->SetNumberField(TEXT("blueprints"), static_cast<double>(Counts.Blueprints));
    CountsJson->SetNumberField(TEXT("blueprint_graphs"), static_cast<double>(Counts.BlueprintGraphs));
    CountsJson->SetNumberField(TEXT("blueprint_nodes"), static_cast<double>(Counts.BlueprintNodes));
    CountsJson->SetNumberField(TEXT("blueprint_edges"), static_cast<double>(Counts.BlueprintEdges));
    CountsJson->SetNumberField(TEXT("blueprint_variables"), static_cast<double>(Counts.BlueprintVariables));
    CountsJson->SetNumberField(TEXT("blueprint_components"), static_cast<double>(Counts.BlueprintComponents));
    Manifest->SetObjectField(TEXT("counts"), CountsJson);

    if (!SaveJsonObject(FPaths::Combine(OutputDir, TEXT("manifest.json")), Manifest))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetTool: could not write manifest.json."));
        return 5;
    }

    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: indexed %lld files, %lld assets, %lld blueprints, %lld blueprint nodes."),
        Counts.Files, Counts.Assets, Counts.Blueprints, Counts.BlueprintNodes);
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetTool: output: %s"), *OutputDir);
    return 0;
}

#include "UnrealAssetToolCommandlet.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AnimationConduitGraphSchema.h"
#include "AnimationGraph.h"
#include "AnimationStateGraph.h"
#include "AnimationStateMachineGraph.h"
#include "AnimationTransitionGraph.h"
#include "AnimGraphNode_LinkedAnimLayer.h"
#include "AnimGraphNode_LinkedInputPose.h"
#include "AnimGraphNode_Root.h"
#include "AnimGraphNode_SaveCachedPose.h"
#include "AnimGraphNode_SequencePlayer.h"
#include "AnimGraphNode_Slot.h"
#include "AnimGraphNode_StateMachineBase.h"
#include "AnimGraphNode_StateResult.h"
#include "AnimGraphNode_TransitionResult.h"
#include "AnimGraphNode_UseCachedPose.h"
#include "AnimStateAliasNode.h"
#include "AnimStateConduitNode.h"
#include "AnimStateEntryNode.h"
#include "AnimStateNode.h"
#include "AnimStateNodeBase.h"
#include "AnimStateTransitionNode.h"
#include "Dom/JsonObject.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraph/EdGraphSchema.h"
#include "EdGraphNode_Comment.h"
#include "Engine/Blueprint.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "K2Node.h"
#include "K2Node_CallFunction.h"
#include "K2Node_CustomEvent.h"
#include "K2Node_DynamicCast.h"
#include "K2Node_Event.h"
#include "K2Node_ExecutionSequence.h"
#include "K2Node_FunctionEntry.h"
#include "K2Node_FunctionResult.h"
#include "K2Node_IfThenElse.h"
#include "K2Node_Knot.h"
#include "K2Node_MacroInstance.h"
#include "K2Node_Select.h"
#include "K2Node_Self.h"
#include "K2Node_SpawnActorFromClass.h"
#include "K2Node_Switch.h"
#include "K2Node_Tunnel.h"
#include "K2Node_Variable.h"
#include "K2Node_VariableGet.h"
#include "K2Node_VariableSet.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UnrealType.h"
#include "UObject/UObjectGlobals.h"

namespace UnrealAssetTool
{
    static constexpr int32 SchemaVersion = 5;
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
        int64 BlueprintSemanticNodes = 0;
        int64 BlueprintNodeProperties = 0;
        int64 BlueprintNodeReferences = 0;
        int64 BlueprintBindings = 0;
        int64 RigVMObjects = 0;
        int64 RigVMProperties = 0;
        int64 RigVMReferences = 0;
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
        // Prefer concrete animation graph classes over the generic Blueprint
        // graph arrays. This tells retrieval whether a graph is an AnimGraph,
        // state machine, state body, transition rule, or conduit rule.
        if (Graph->IsA<UAnimationStateMachineGraph>()) return TEXT("anim_state_machine");
        if (Graph->IsA<UAnimationStateGraph>()) return TEXT("anim_state");
        if (Graph->IsA<UAnimationTransitionGraph>()) return TEXT("anim_transition");
        if (Graph->GetSchema() && Graph->GetSchema()->IsA<UAnimationConduitGraphSchema>()) return TEXT("anim_conduit");
        if (Graph->IsA<UAnimationGraph>()) return TEXT("anim_graph");

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

    static void AddMemberReferenceFields(
        FMemberReference& Reference,
        UClass* SelfScope,
        const TSharedRef<FJsonObject>& Semantic,
        FString& OutSymbol,
        FString& OutOwner)
    {
        OutSymbol = Reference.GetMemberName().ToString();
        Semantic->SetStringField(TEXT("member_name"), OutSymbol);
        Semantic->SetStringField(TEXT("member_guid"), Reference.GetMemberGuid().ToString(EGuidFormats::DigitsWithHyphensLower));
        Semantic->SetStringField(TEXT("member_scope"), Reference.GetMemberScopeName());
        Semantic->SetBoolField(TEXT("self_context"), Reference.IsSelfContext());
        Semantic->SetBoolField(TEXT("local_scope"), Reference.IsLocalScope());

        UClass* ParentClass = Reference.GetMemberParentClass(SelfScope);
        if (!ParentClass)
        {
            ParentClass = Reference.GetScope(SelfScope);
        }
        OutOwner = ParentClass ? ParentClass->GetPathName() : TEXT("");
        Semantic->SetStringField(TEXT("member_parent_class"), OutOwner);
    }

    static FString GetPinDefaultObjectPath(const UEdGraphNode* Node, const FName PinName)
    {
        if (!Node)
        {
            return TEXT("");
        }

        for (const UEdGraphPin* Pin : Node->Pins)
        {
            if (Pin && Pin->PinName == PinName && Pin->DefaultObject)
            {
                return Pin->DefaultObject->GetPathName();
            }
        }
        return TEXT("");
    }

    static FString ExportReflectedPropertyText(UObject* Object, const FName PropertyName)
    {
        if (!Object)
        {
            return TEXT("");
        }

        FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
        if (!Property)
        {
            return TEXT("");
        }

        FString Value;
        Property->ExportText_InContainer(
            0,
            Value,
            Object,
            nullptr,
            Object,
            PPF_None,
            nullptr);
        return Value;
    }

    static UObject* GetReflectedObjectProperty(UObject* Object, const FName PropertyName)
    {
        if (!Object)
        {
            return nullptr;
        }

        FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(
            Object->GetClass()->FindPropertyByName(PropertyName));
        return Property ? Property->GetObjectPropertyValue_InContainer(Object) : nullptr;
    }

    static UObject* GetReflectedStructObjectProperty(
        UObject* Object,
        const FName StructPropertyName,
        const FName ChildPropertyName)
    {
        if (!Object)
        {
            return nullptr;
        }

        FStructProperty* StructProperty = CastField<FStructProperty>(
            Object->GetClass()->FindPropertyByName(StructPropertyName));
        if (!StructProperty || !StructProperty->Struct)
        {
            return nullptr;
        }

        FObjectPropertyBase* ChildProperty = CastField<FObjectPropertyBase>(
            StructProperty->Struct->FindPropertyByName(ChildPropertyName));
        if (!ChildProperty)
        {
            return nullptr;
        }

        const void* StructValue = StructProperty->ContainerPtrToValuePtr<void>(Object);
        const void* ChildValue = ChildProperty->ContainerPtrToValuePtr<void>(StructValue);
        return ChildProperty->GetObjectPropertyValue(ChildValue);
    }

    static UObject* GetReflectedNestedObjectProperty(
        UObject* Object,
        const TArray<FName>& PropertyPath)
    {
        if (!Object || PropertyPath.IsEmpty())
        {
            return nullptr;
        }

        const UStruct* CurrentStruct = Object->GetClass();
        const void* CurrentContainer = Object;

        for (int32 Index = 0; Index < PropertyPath.Num(); ++Index)
        {
            if (!CurrentStruct || !CurrentContainer)
            {
                return nullptr;
            }

            FProperty* Property = CurrentStruct->FindPropertyByName(PropertyPath[Index]);
            if (!Property)
            {
                return nullptr;
            }

            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(CurrentContainer);
            const bool bLast = Index == PropertyPath.Num() - 1;
            if (bLast)
            {
                if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    return ObjectProperty->GetObjectPropertyValue(ValuePtr);
                }
                return nullptr;
            }

            const FStructProperty* StructProperty = CastField<FStructProperty>(Property);
            if (!StructProperty || !StructProperty->Struct)
            {
                return nullptr;
            }

            CurrentStruct = StructProperty->Struct;
            CurrentContainer = ValuePtr;
        }

        return nullptr;
    }

    static TArray<FString> GetReflectedStructArrayFieldTexts(
        UObject* Object,
        const FName StructPropertyName,
        const FName ArrayPropertyName,
        const FName ElementFieldName)
    {
        TArray<FString> Result;
        if (!Object)
        {
            return Result;
        }

        FStructProperty* StructProperty = CastField<FStructProperty>(
            Object->GetClass()->FindPropertyByName(StructPropertyName));
        if (!StructProperty || !StructProperty->Struct)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            StructProperty->Struct->FindPropertyByName(ArrayPropertyName));
        FStructProperty* InnerStructProperty = ArrayProperty
            ? CastField<FStructProperty>(ArrayProperty->Inner)
            : nullptr;
        if (!ArrayProperty || !InnerStructProperty || !InnerStructProperty->Struct)
        {
            return Result;
        }

        FProperty* ElementField = InnerStructProperty->Struct->FindPropertyByName(ElementFieldName);
        if (!ElementField)
        {
            return Result;
        }

        const void* StructValue = StructProperty->ContainerPtrToValuePtr<void>(Object);
        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(StructValue);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* ElementValue = Helper.GetRawPtr(Index);
            const void* FieldValue = ElementField->ContainerPtrToValuePtr<void>(ElementValue);
            FString FieldText;
            ElementField->ExportTextItem_Direct(
                FieldText,
                FieldValue,
                nullptr,
                Object,
                PPF_None,
                nullptr);
            Result.Add(MoveTemp(FieldText));
        }
        return Result;
    }

    static TArray<FString> GetReflectedArrayElementTexts(UObject* Object, const FName PropertyName)
    {
        TArray<FString> Result;
        if (!Object)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            Object->GetClass()->FindPropertyByName(PropertyName));
        if (!ArrayProperty || !ArrayProperty->Inner)
        {
            return Result;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            FString ElementText;
            ArrayProperty->Inner->ExportTextItem_Direct(
                ElementText,
                Helper.GetRawPtr(Index),
                nullptr,
                Object,
                PPF_None,
                nullptr);
            Result.Add(MoveTemp(ElementText));
        }
        return Result;
    }

    static void ApplyReflectedSemanticEnrichment(
        UBlueprint* Blueprint,
        UEdGraphNode* Node,
        const TSharedRef<FJsonObject>& Semantic,
        FString& OutOperation,
        FString& OutSymbol,
        FString& OutOwner)
    {
        if (!Node)
        {
            return;
        }

        const auto SetAssetReference = [&OutSymbol, &OutOwner, &Semantic](
            const TCHAR* FieldName,
            UObject* Asset)
        {
            if (!Asset)
            {
                return;
            }
            const FString AssetPath = Asset->GetPathName();
            OutSymbol = Asset->GetName();
            OutOwner = AssetPath;
            Semantic->SetStringField(FieldName, AssetPath);
            Semantic->SetStringField(
                FString::Printf(TEXT("%s_class"), FieldName),
                Asset->GetClass()->GetPathName());
        };

        if (OutOperation == TEXT("property_access"))
        {
            const FString TextPath = ExportReflectedPropertyText(Node, TEXT("TextPath"));
            if (!TextPath.IsEmpty())
            {
                OutSymbol = TextPath;
                Semantic->SetStringField(TEXT("access_path"), TextPath);
            }

            const TArray<FString> Segments = GetReflectedArrayElementTexts(Node, TEXT("Path"));
            TArray<TSharedPtr<FJsonValue>> SegmentJson;
            SegmentJson.Reserve(Segments.Num());
            for (const FString& Segment : Segments)
            {
                SegmentJson.Add(MakeShared<FJsonValueString>(Segment));
            }
            Semantic->SetArrayField(TEXT("path_segments"), SegmentJson);
        }
        else if (OutOperation == TEXT("evaluate_chooser"))
        {
            SetAssetReference(TEXT("chooser_asset"), GetReflectedObjectProperty(Node, TEXT("Chooser")));
        }
        else if (OutOperation == TEXT("evaluate_proxy"))
        {
            SetAssetReference(TEXT("proxy_asset"), GetReflectedObjectProperty(Node, TEXT("Proxy")));
        }
        else if (OutOperation == TEXT("anim_blend_space_player"))
        {
            SetAssetReference(
                TEXT("blend_space"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("BlendSpace")));
        }
        else if (OutOperation == TEXT("anim_sequence_evaluator"))
        {
            SetAssetReference(
                TEXT("animation_asset"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("Sequence")));
        }
        else if (OutOperation == TEXT("anim_pose_driver"))
        {
            SetAssetReference(
                TEXT("pose_asset"),
                GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("PoseAsset")));

            const TArray<FString> SourceBones = GetReflectedStructArrayFieldTexts(
                Node, TEXT("Node"), TEXT("SourceBones"), TEXT("BoneName"));
            TArray<TSharedPtr<FJsonValue>> SourceBoneJson;
            SourceBoneJson.Reserve(SourceBones.Num());
            for (const FString& BoneName : SourceBones)
            {
                SourceBoneJson.Add(MakeShared<FJsonValueString>(BoneName));
            }
            Semantic->SetArrayField(TEXT("source_bones"), SourceBoneJson);
            if (OutSymbol.IsEmpty() && SourceBones.Num() == 1)
            {
                OutSymbol = SourceBones[0];
            }
        }
        else if (OutOperation == TEXT("anim_control_rig"))
        {
            UObject* RigClass = GetReflectedNestedObjectProperty(
                Node,
                TArray<FName>{ FName(TEXT("Node")), FName(TEXT("ControlRigAssetReference")), FName(TEXT("BlueprintRigClass")) });
            if (!RigClass)
            {
                RigClass = GetReflectedNestedObjectProperty(
                    Node,
                    TArray<FName>{ FName(TEXT("Node")), FName(TEXT("DefaultControlRigAssetReference")), FName(TEXT("BlueprintRigClass")) });
            }
            SetAssetReference(TEXT("control_rig_class"), RigClass);
        }
        else if (OutOperation == TEXT("anim_motion_matching"))
        {
            if (UObject* BlendProfile = GetReflectedStructObjectProperty(Node, TEXT("Node"), TEXT("BlendProfile")))
            {
                Semantic->SetStringField(TEXT("blend_profile"), BlendProfile->GetPathName());
            }
        }
        else if (OutOperation == TEXT("control_rig_node"))
        {
            OutSymbol = ExportReflectedPropertyText(Node, TEXT("ModelNodePath"));
            OutOwner = Node->GetGraph() ? Node->GetGraph()->GetPathName() :
                (Blueprint ? Blueprint->GetPathName() : TEXT(""));
            Semantic->SetStringField(TEXT("model_node_path"), OutSymbol);
            Semantic->SetStringField(TEXT("semantic_depth"), TEXT("model_node_reference"));
        }
    }

    static void ApplyClassSemanticFallback(
        UEdGraphNode* Node,
        const TSharedRef<FJsonObject>& Semantic,
        FString& OutOperation,
        FString& OutSymbol,
        FString& OutOwner)
    {
        if (!Node || OutOperation != TEXT("node"))
        {
            return;
        }

        struct FClassSemantic
        {
            const TCHAR* ClassName;
            const TCHAR* Operation;
        };

        static const FClassSemantic KnownClasses[] =
        {
            { TEXT("K2Node_PropertyAccess"), TEXT("property_access") },
            { TEXT("K2Node_EnumEquality"), TEXT("enum_equal") },
            { TEXT("K2Node_EnumInequality"), TEXT("enum_not_equal") },
            { TEXT("K2Node_MakeArray"), TEXT("make_array") },
            { TEXT("K2Node_GetArrayItem"), TEXT("array_get") },
            { TEXT("K2Node_AddDelegate"), TEXT("delegate_bind") },
            { TEXT("K2Node_CreateDelegate"), TEXT("delegate_create") },
            { TEXT("K2Node_CallDelegate"), TEXT("delegate_call") },
            { TEXT("K2Node_GetEnumeratorNameAsString"), TEXT("enum_to_string") },
            { TEXT("K2Node_VariableSetRef"), TEXT("variable_set_ref") },
            { TEXT("K2Node_InputKey"), TEXT("input_key") },
            { TEXT("K2Node_EnhancedInputAction"), TEXT("enhanced_input_event") },
            { TEXT("K2Node_GetInputActionValue"), TEXT("enhanced_input_value") },
            { TEXT("K2Node_GetSubsystem"), TEXT("get_subsystem") },
            { TEXT("K2Node_GetEngineSubsystem"), TEXT("get_engine_subsystem") },
            { TEXT("K2Node_GetEditorSubsystem"), TEXT("get_editor_subsystem") },
            { TEXT("K2Node_GetSubsystemFromPC"), TEXT("get_subsystem_from_player_controller") },
            { TEXT("K2Node_FormatText"), TEXT("format_text") },
            { TEXT("K2Node_ConvertAsset"), TEXT("convert_asset") },
            { TEXT("K2Node_GetClassDefaults"), TEXT("get_class_defaults") },
            { TEXT("K2Node_Timeline"), TEXT("timeline") },
            { TEXT("K2Node_LoadAssetClass"), TEXT("load_asset_class") },
            { TEXT("K2Node_CreateWidget"), TEXT("create_widget") },
            { TEXT("K2Node_EvaluateChooser2"), TEXT("evaluate_chooser") },
            { TEXT("K2Node_GetChooserContextParameters"), TEXT("chooser_context_parameters") },
            { TEXT("K2Node_PlayMontageOnMoverActor"), TEXT("mover_play_montage") },
            { TEXT("K2Node_PlayMontage"), TEXT("anim_play_montage") },
            { TEXT("K2Node_AnimNodeReference"), TEXT("anim_node_reference") },

            { TEXT("AnimGraphNode_PoseDriver"), TEXT("anim_pose_driver") },
            { TEXT("AnimGraphNode_LocalToComponentSpace"), TEXT("anim_local_to_component_space") },
            { TEXT("AnimGraphNode_ComponentToLocalSpace"), TEXT("anim_component_to_local_space") },
            { TEXT("AnimGraphNode_ControlRig"), TEXT("anim_control_rig") },
            { TEXT("AnimGraphNode_ModifyCurve"), TEXT("anim_modify_curve") },
            { TEXT("AnimGraphNode_ModifyBone"), TEXT("anim_modify_bone") },
            { TEXT("AnimGraphNode_BlendSpacePlayer"), TEXT("anim_blend_space_player") },
            { TEXT("AnimGraphNode_SequenceEvaluator"), TEXT("anim_sequence_evaluator") },
            { TEXT("AnimGraphNode_BlendListByBool"), TEXT("anim_blend_by_bool") },
            { TEXT("AnimGraphNode_BlendListByEnum"), TEXT("anim_blend_by_enum") },
            { TEXT("AnimGraphNode_BlendListByInt"), TEXT("anim_blend_by_int") },
            { TEXT("AnimGraphNode_TwoWayBlend"), TEXT("anim_two_way_blend") },
            { TEXT("AnimGraphNode_ApplyMeshSpaceAdditive"), TEXT("anim_apply_mesh_space_additive") },
            { TEXT("AnimGraphNode_RigidBody"), TEXT("anim_rigid_body") },
            { TEXT("AnimGraphNode_CopyBone"), TEXT("anim_copy_bone") },
            { TEXT("AnimGraphNode_CopyPoseFromMesh"), TEXT("anim_copy_pose_from_mesh") },
            { TEXT("AnimGraphNode_TransitionPoseEvaluator"), TEXT("anim_transition_pose_evaluator") },
            { TEXT("AnimGraphNode_ResetRoot"), TEXT("anim_reset_root") },
            { TEXT("AnimGraphNode_DeadBlending"), TEXT("anim_dead_blending") },
            { TEXT("AnimGraphNode_Constraint"), TEXT("anim_constraint") },
            { TEXT("AnimGraphNode_LegIK"), TEXT("anim_leg_ik") },
            { TEXT("AnimGraphNode_Inertialization"), TEXT("anim_inertialization") },
            { TEXT("AnimGraphNode_IdentityPose"), TEXT("anim_identity_pose") },

            { TEXT("AnimGraphNode_Steering"), TEXT("anim_steering") },
            { TEXT("AnimGraphNode_OrientationWarping"), TEXT("anim_orientation_warping") },
            { TEXT("AnimGraphNode_OffsetRootBone"), TEXT("anim_offset_root_bone") },
            { TEXT("AnimGraphNode_BlendStackInput"), TEXT("anim_blend_stack_input") },
            { TEXT("AnimGraphNode_BlendStack"), TEXT("anim_blend_stack") },
            { TEXT("AnimGraphNode_RetargetPoseFromMesh"), TEXT("anim_retarget_pose_from_mesh") },
            { TEXT("AnimGraphNode_PoseSearchHistoryCollector"), TEXT("anim_pose_search_history") },
            { TEXT("AnimGraphNode_PoseSearchComponentSpaceHistoryCollector"), TEXT("anim_pose_search_component_history") },
            { TEXT("AnimGraphNode_MotionMatching"), TEXT("anim_motion_matching") },
            { TEXT("AnimGraphNode_LayeredBoneBlend"), TEXT("anim_layered_bone_blend") },
            { TEXT("AnimGraphNode_LocalRefPose"), TEXT("anim_local_ref_pose") },
            { TEXT("AnimGraphNode_PoseBlendNode"), TEXT("anim_pose_blend") },
            { TEXT("AnimGraphNode_PoseSnapshot"), TEXT("anim_pose_snapshot") },
            { TEXT("AnimGraphNode_FootPlacement"), TEXT("anim_foot_placement") },
            { TEXT("AnimGraphNode_StrideWarping"), TEXT("anim_stride_warping") },
            { TEXT("AnimGraphNode_RemapCurves"), TEXT("anim_remap_curves") },
            { TEXT("AnimGraphNode_LiveLinkPose"), TEXT("anim_live_link_pose") },
            { TEXT("AnimGraphNode_RigLogic"), TEXT("anim_rig_logic") },

            { TEXT("K2Node_AddComponentByClass"), TEXT("add_component_by_class") },
            { TEXT("K2Node_AssignDelegate"), TEXT("delegate_assign") },
            { TEXT("K2Node_CastByteToEnum"), TEXT("cast_byte_to_enum") },
            { TEXT("K2Node_GenericCreateObject"), TEXT("create_object") },
            { TEXT("K2Node_LoadAsset"), TEXT("load_asset") },
            { TEXT("K2Node_MakeMap"), TEXT("make_map") },
            { TEXT("K2Node_MapForEach"), TEXT("map_for_each") },
            { TEXT("K2Node_LatentGameplayTaskCall"), TEXT("gameplay_task_call") },
            { TEXT("K2Node_InputDebugKey"), TEXT("input_debug_key") },
            { TEXT("K2Node_EvaluateLiveLinkFrameWithSpecificRole"), TEXT("evaluate_live_link_frame") },
            { TEXT("K2Node_EvaluateProxy2"), TEXT("evaluate_proxy") },
            { TEXT("ControlRigGraphNode"), TEXT("control_rig_node") }
        };

        const FString ClassName = Node->GetClass()->GetName();
        for (const FClassSemantic& Entry : KnownClasses)
        {
            if (ClassName == Entry.ClassName)
            {
                OutOperation = Entry.Operation;
                Semantic->SetStringField(TEXT("classification_source"), TEXT("node_class"));
                Semantic->SetStringField(TEXT("concrete_node_class"), Node->GetClass()->GetPathName());
                break;
            }
        }

        if (OutOperation == TEXT("enhanced_input_event") ||
            OutOperation == TEXT("enhanced_input_value"))
        {
            const FString InputActionPath = GetPinDefaultObjectPath(Node, TEXT("InputAction"));
            if (!InputActionPath.IsEmpty())
            {
                OutOwner = InputActionPath;
                OutSymbol = FPackageName::ObjectPathToObjectName(InputActionPath);
                Semantic->SetStringField(TEXT("input_action"), InputActionPath);
            }
        }
    }

    struct FNodePropertyScanContext
    {
        UEdGraphNode* Node = nullptr;
        FString NodeId;
        FString BlueprintPath;
        FString GraphName;
        FJsonlWriter* PropertiesWriter = nullptr;
        FJsonlWriter* ReferencesWriter = nullptr;
        FScanCounts* Counts = nullptr;
        TSet<const UObject*> VisitedObjects;
    };

    static bool IsCapturableProperty(const FProperty* Property)
    {
        return Property &&
            !Property->HasAnyPropertyFlags(
                CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient);
    }

    static bool WriteNodePropertyRecord(
        FNodePropertyScanContext& Context,
        FProperty* Property,
        const void* ValuePtr,
        const FString& PropertyPath,
        const FString& DeclaringType,
        int32 Depth)
    {
        if (!Property || !ValuePtr || !Context.PropertiesWriter || !Context.ReferencesWriter || !Context.Counts)
        {
            return true;
        }

        static constexpr int32 MaxExportedPropertyChars = 65536;

        FString Value;
        Property->ExportTextItem_Direct(
            Value,
            ValuePtr,
            nullptr,
            Context.Node,
            PPF_None,
            nullptr);

        bool bTruncated = false;
        if (Value.Len() > MaxExportedPropertyChars)
        {
            Value = Value.Left(MaxExportedPropertyChars);
            bTruncated = true;
        }

        FString ObjectPath;
        FString ObjectClass;
        UObject* ObjectValue = nullptr;
        if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
        {
            ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
            if (ObjectValue)
            {
                ObjectPath = ObjectValue->GetPathName();
                ObjectClass = ObjectValue->GetClass()->GetPathName();
            }
        }

        const TSharedRef<FJsonObject> PropertyJson = MakeShared<FJsonObject>();
        PropertyJson->SetStringField(TEXT("node_id"), Context.NodeId);
        PropertyJson->SetStringField(TEXT("blueprint_path"), Context.BlueprintPath);
        PropertyJson->SetStringField(TEXT("graph_name"), Context.GraphName);
        PropertyJson->SetStringField(TEXT("node_class"), Context.Node->GetClass()->GetPathName());
        PropertyJson->SetStringField(TEXT("property_name"), Property->GetName());
        PropertyJson->SetStringField(TEXT("property_path"), PropertyPath);
        PropertyJson->SetStringField(TEXT("owner_class"), DeclaringType);
        PropertyJson->SetStringField(TEXT("declaring_type"), DeclaringType);
        PropertyJson->SetNumberField(TEXT("depth"), Depth);
        PropertyJson->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
        PropertyJson->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
        PropertyJson->SetStringField(TEXT("value"), Value);
        PropertyJson->SetStringField(TEXT("object_path"), ObjectPath);
        PropertyJson->SetStringField(TEXT("object_class"), ObjectClass);
        PropertyJson->SetNumberField(TEXT("property_flags"), static_cast<double>(Property->GetPropertyFlags()));
        PropertyJson->SetBoolField(TEXT("truncated"), bTruncated);

        if (!Context.PropertiesWriter->Write(PropertyJson))
        {
            return false;
        }
        ++Context.Counts->BlueprintNodeProperties;

        if (ObjectValue)
        {
            const TSharedRef<FJsonObject> ReferenceJson = MakeShared<FJsonObject>();
            ReferenceJson->SetStringField(TEXT("node_id"), Context.NodeId);
            ReferenceJson->SetStringField(TEXT("blueprint_path"), Context.BlueprintPath);
            ReferenceJson->SetStringField(TEXT("graph_name"), Context.GraphName);
            ReferenceJson->SetStringField(TEXT("node_class"), Context.Node->GetClass()->GetPathName());
            ReferenceJson->SetStringField(TEXT("property_path"), PropertyPath);
            ReferenceJson->SetStringField(TEXT("target_object_path"), ObjectPath);
            ReferenceJson->SetStringField(TEXT("target_class"), ObjectClass);
            ReferenceJson->SetBoolField(TEXT("node_owned"), ObjectValue->GetOuter() == Context.Node);

            if (!Context.ReferencesWriter->Write(ReferenceJson))
            {
                return false;
            }
            ++Context.Counts->BlueprintNodeReferences;
        }

        return true;
    }

    static bool ScanReflectedPropertyValue(
        FNodePropertyScanContext& Context,
        FProperty* Property,
        const void* ContainerPtr,
        const FString& PropertyPath,
        const FString& DeclaringType,
        int32 Depth);

    static bool ScanOwnedBindingObject(
        FNodePropertyScanContext& Context,
        UObject* ObjectValue,
        const FString& Prefix,
        int32 Depth)
    {
        if (!ObjectValue || Context.VisitedObjects.Contains(ObjectValue))
        {
            return true;
        }

        // Binding objects are editor-owned subobjects that contain the actual
        // property-access bindings for many AnimGraph pins. Do not recursively
        // walk arbitrary node-owned graphs/assets, which would explode the scan
        // and create cycles.
        if (!ObjectValue->GetClass()->GetName().Contains(TEXT("Binding")))
        {
            return true;
        }

        Context.VisitedObjects.Add(ObjectValue);

        for (UClass* Class = ObjectValue->GetClass();
             Class && Class != UObject::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }

                const FString ChildPath = FString::Printf(
                    TEXT("%s.%s"),
                    *Prefix,
                    *Property->GetName());
                if (!ScanReflectedPropertyValue(
                        Context,
                        Property,
                        ObjectValue,
                        ChildPath,
                        Class->GetPathName(),
                        Depth))
                {
                    return false;
                }
            }
        }
        return true;
    }

    static bool ScanReflectedPropertyValue(
        FNodePropertyScanContext& Context,
        FProperty* Property,
        const void* ContainerPtr,
        const FString& PropertyPath,
        const FString& DeclaringType,
        int32 Depth)
    {
        if (!IsCapturableProperty(Property) || !ContainerPtr)
        {
            return true;
        }

        static constexpr int32 MaxNestedDepth = 4;
        static constexpr int32 MaxSimpleArrayElements = 64;

        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(ContainerPtr);
        if (!ValuePtr)
        {
            return true;
        }

        if (!WriteNodePropertyRecord(
                Context,
                Property,
                ValuePtr,
                PropertyPath,
                DeclaringType,
                Depth))
        {
            return false;
        }

        if (Depth >= MaxNestedDepth)
        {
            return true;
        }

        if (FStructProperty* StructProperty = CastField<FStructProperty>(Property))
        {
            if (!StructProperty->Struct)
            {
                return true;
            }

            for (TFieldIterator<FProperty> It(StructProperty->Struct, EFieldIterationFlags::Default); It; ++It)
            {
                FProperty* ChildProperty = *It;
                if (!IsCapturableProperty(ChildProperty))
                {
                    continue;
                }

                const FString ChildPath = FString::Printf(
                    TEXT("%s.%s"),
                    *PropertyPath,
                    *ChildProperty->GetName());
                if (!ScanReflectedPropertyValue(
                        Context,
                        ChildProperty,
                        ValuePtr,
                        ChildPath,
                        StructProperty->Struct->GetPathName(),
                        Depth + 1))
                {
                    return false;
                }
            }
        }
        else if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
        {
            FProperty* Inner = ArrayProperty->Inner;
            if (!Inner ||
                CastField<FStructProperty>(Inner) ||
                CastField<FArrayProperty>(Inner) ||
                CastField<FSetProperty>(Inner) ||
                CastField<FMapProperty>(Inner))
            {
                return true;
            }

            FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
            const int32 NumToWrite = FMath::Min(Helper.Num(), MaxSimpleArrayElements);
            for (int32 Index = 0; Index < NumToWrite; ++Index)
            {
                const void* ElementValue = Helper.GetRawPtr(Index);
                const FString ElementPath = FString::Printf(
                    TEXT("%s[%d]"),
                    *PropertyPath,
                    Index);
                if (!WriteNodePropertyRecord(
                        Context,
                        Inner,
                        ElementValue,
                        ElementPath,
                        DeclaringType,
                        Depth + 1))
                {
                    return false;
                }
            }
        }
        else if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
        {
            UObject* ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
            if (ObjectValue && ObjectValue->GetOuter() == Context.Node)
            {
                if (!ScanOwnedBindingObject(Context, ObjectValue, PropertyPath, Depth + 1))
                {
                    return false;
                }
            }
        }

        return true;
    }

    static bool ScanNodeProperties(
        UEdGraphNode* Node,
        const FString& NodeId,
        const FString& BlueprintPath,
        const FString& GraphName,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FScanCounts& Counts)
    {
        if (!Node)
        {
            return true;
        }

        FNodePropertyScanContext Context;
        Context.Node = Node;
        Context.NodeId = NodeId;
        Context.BlueprintPath = BlueprintPath;
        Context.GraphName = GraphName;
        Context.PropertiesWriter = &PropertiesWriter;
        Context.ReferencesWriter = &ReferencesWriter;
        Context.Counts = &Counts;
        Context.VisitedObjects.Add(Node);

        for (UClass* Class = Node->GetClass();
             Class && Class != UEdGraphNode::StaticClass() && Class != UK2Node::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }

                if (!ScanReflectedPropertyValue(
                        Context,
                        Property,
                        Node,
                        Property->GetName(),
                        Class->GetPathName(),
                        0))
                {
                    return false;
                }
            }
        }
        return true;
    }

    static TSharedRef<FJsonObject> BuildNodeSemantic(
        UBlueprint* Blueprint,
        UEdGraphNode* Node,
        FString& OutOperation,
        FString& OutSymbol,
        FString& OutOwner)
    {
        const TSharedRef<FJsonObject> Semantic = MakeShared<FJsonObject>();
        OutOperation = TEXT("node");
        OutSymbol.Reset();
        OutOwner.Reset();

        UClass* SelfScope = Blueprint
            ? (Blueprint->SkeletonGeneratedClass ? Blueprint->SkeletonGeneratedClass : Blueprint->GeneratedClass)
            : nullptr;

        const auto SetBoundGraph = [&Semantic](const TCHAR* FieldName, UEdGraph* BoundGraph)
        {
            Semantic->SetStringField(FieldName, BoundGraph ? BoundGraph->GetPathName() : TEXT(""));
        };

        // -----------------------------------------------------------------
        // Animation Blueprint semantics
        // -----------------------------------------------------------------
        if (UAnimGraphNode_StateMachineBase* StateMachine = Cast<UAnimGraphNode_StateMachineBase>(Node))
        {
            OutOperation = TEXT("anim_state_machine");
            OutSymbol = StateMachine->GetStateMachineName();
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("state_machine_name"), OutSymbol);
            SetBoundGraph(TEXT("editor_state_machine_graph"), StateMachine->EditorStateMachineGraph.Get());
        }
        else if (UAnimStateEntryNode* Entry = Cast<UAnimStateEntryNode>(Node))
        {
            OutOperation = TEXT("anim_state_entry");
            if (UAnimStateNodeBase* TargetState = Cast<UAnimStateNodeBase>(Entry->GetOutputNode()))
            {
                OutSymbol = TargetState->GetStateName();
                Semantic->SetStringField(TEXT("target_state"), OutSymbol);
                Semantic->SetStringField(TEXT("target_node_guid"),
                    TargetState->NodeGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
            }
        }
        else if (UAnimStateTransitionNode* Transition = Cast<UAnimStateTransitionNode>(Node))
        {
            OutOperation = TEXT("anim_transition");

            UAnimStateNodeBase* PreviousState = Transition->GetPreviousState();
            UAnimStateNodeBase* NextState = Transition->GetNextState();
            const FString PreviousName = PreviousState ? PreviousState->GetStateName() : TEXT("");
            const FString NextName = NextState ? NextState->GetStateName() : TEXT("");

            if (!PreviousName.IsEmpty() || !NextName.IsEmpty())
            {
                OutSymbol = FString::Printf(TEXT("%s -> %s"), *PreviousName, *NextName);
            }
            OutOwner = Transition->GetGraph() ? Transition->GetGraph()->GetPathName() : TEXT("");

            Semantic->SetStringField(TEXT("previous_state"), PreviousName);
            Semantic->SetStringField(TEXT("next_state"), NextName);
            Semantic->SetBoolField(TEXT("bidirectional"), Transition->Bidirectional);
            Semantic->SetBoolField(TEXT("disabled"), Transition->bDisabled);
            Semantic->SetBoolField(TEXT("automatic_rule"),
                Transition->bAutomaticRuleBasedOnSequencePlayerInState);
            Semantic->SetNumberField(TEXT("automatic_rule_trigger_time"),
                Transition->AutomaticRuleTriggerTime);
            Semantic->SetNumberField(TEXT("crossfade_duration"), Transition->CrossfadeDuration);
            Semantic->SetNumberField(TEXT("priority_order"), Transition->PriorityOrder);
            Semantic->SetNumberField(TEXT("logic_type"), static_cast<int32>(Transition->LogicType));
            Semantic->SetNumberField(TEXT("min_time_before_reentry"), Transition->MinTimeBeforeReentry);
            Semantic->SetBoolField(TEXT("only_evaluate_when_active"), Transition->bOnlyEvaluateWhenActive);
            Semantic->SetBoolField(TEXT("allow_inertialization_for_self_transitions"),
                Transition->bAllowInertializationForSelfTransitions);
            Semantic->SetBoolField(TEXT("shared_rules"), Transition->bSharedRules);
            Semantic->SetStringField(TEXT("shared_rules_name"), Transition->SharedRulesName);
            Semantic->SetBoolField(TEXT("shared_crossfade"), Transition->bSharedCrossfade);
            Semantic->SetStringField(TEXT("shared_crossfade_name"), Transition->SharedCrossfadeName);
            SetBoundGraph(TEXT("rule_graph"), Transition->BoundGraph.Get());
            SetBoundGraph(TEXT("custom_transition_graph"), Transition->CustomTransitionGraph.Get());
        }
        else if (UAnimStateNode* State = Cast<UAnimStateNode>(Node))
        {
            OutOperation = TEXT("anim_state");
            OutSymbol = State->GetStateName();
            OutOwner = State->GetGraph() ? State->GetGraph()->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("state_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("always_reset_on_entry"), State->bAlwaysResetOnEntry);
            Semantic->SetNumberField(TEXT("state_type"), static_cast<int32>(State->StateType));
            SetBoundGraph(TEXT("bound_graph"), State->GetBoundGraph());
        }
        else if (UAnimStateConduitNode* Conduit = Cast<UAnimStateConduitNode>(Node))
        {
            OutOperation = TEXT("anim_conduit");
            OutSymbol = Conduit->GetStateName();
            OutOwner = Conduit->GetGraph() ? Conduit->GetGraph()->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("conduit_name"), OutSymbol);
            SetBoundGraph(TEXT("bound_graph"), Conduit->GetBoundGraph());
        }
        else if (UAnimStateAliasNode* Alias = Cast<UAnimStateAliasNode>(Node))
        {
            OutOperation = TEXT("anim_state_alias");
            OutSymbol = Alias->StateAliasName;
            OutOwner = Alias->GetGraph() ? Alias->GetGraph()->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("alias_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("global_alias"), Alias->bGlobalAlias);

            TArray<TSharedPtr<FJsonValue>> AliasedStates;
            for (const TWeakObjectPtr<UAnimStateNodeBase>& AliasedWeak : Alias->GetAliasedStates())
            {
                if (UAnimStateNodeBase* AliasedState = AliasedWeak.Get())
                {
                    AliasedStates.Add(MakeShared<FJsonValueString>(AliasedState->GetStateName()));
                }
            }
            Semantic->SetArrayField(TEXT("aliased_states"), AliasedStates);
        }
        else if (UAnimGraphNode_SaveCachedPose* SavePose = Cast<UAnimGraphNode_SaveCachedPose>(Node))
        {
            OutOperation = TEXT("anim_save_cached_pose");
            OutSymbol = SavePose->CacheName;
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("cache_name"), OutSymbol);
        }
        else if (UAnimGraphNode_UseCachedPose* UsePose = Cast<UAnimGraphNode_UseCachedPose>(Node))
        {
            OutOperation = TEXT("anim_use_cached_pose");
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            if (UAnimGraphNode_SaveCachedPose* CachedSavePose = UsePose->SaveCachedPoseNode.Get())
            {
                OutSymbol = CachedSavePose->CacheName;
                Semantic->SetStringField(TEXT("cache_name"), OutSymbol);
                Semantic->SetStringField(TEXT("save_node_guid"),
                    CachedSavePose->NodeGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
            }
        }
        else if (UAnimGraphNode_LinkedAnimLayer* LinkedLayer = Cast<UAnimGraphNode_LinkedAnimLayer>(Node))
        {
            OutOperation = TEXT("anim_linked_layer");
            OutSymbol = LinkedLayer->Node.Layer.ToString();
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("layer_name"), OutSymbol);
            Semantic->SetStringField(TEXT("interface_guid"),
                LinkedLayer->InterfaceGuid.ToString(EGuidFormats::DigitsWithHyphensLower));
        }
        else if (UAnimGraphNode_LinkedInputPose* LinkedInput = Cast<UAnimGraphNode_LinkedInputPose>(Node))
        {
            OutOperation = TEXT("anim_linked_input_pose");
            OutSymbol = LinkedInput->Node.Name.ToString();
            Semantic->SetStringField(TEXT("pose_name"), OutSymbol);
            Semantic->SetNumberField(TEXT("input_pose_index"), LinkedInput->InputPoseIndex);

            FString ReferenceSymbol;
            FString ReferenceOwner;
            AddMemberReferenceFields(
                LinkedInput->FunctionReference,
                SelfScope,
                Semantic,
                ReferenceSymbol,
                ReferenceOwner);
            OutOwner = ReferenceOwner;
            Semantic->SetStringField(TEXT("function_reference_name"), ReferenceSymbol);
        }
        else if (UAnimGraphNode_Slot* Slot = Cast<UAnimGraphNode_Slot>(Node))
        {
            OutOperation = TEXT("anim_slot");
            OutSymbol = Slot->Node.SlotName.ToString();
            OutOwner = Blueprint ? Blueprint->GetPathName() : TEXT("");
            Semantic->SetStringField(TEXT("slot_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("always_update_source_pose"), Slot->Node.bAlwaysUpdateSourcePose);
        }
        else if (UAnimGraphNode_SequencePlayer* SequencePlayer = Cast<UAnimGraphNode_SequencePlayer>(Node))
        {
            OutOperation = TEXT("anim_sequence_player");
            if (UAnimationAsset* AnimationAsset = SequencePlayer->GetAnimationAsset())
            {
                OutSymbol = AnimationAsset->GetName();
                OutOwner = AnimationAsset->GetPathName();
                Semantic->SetStringField(TEXT("animation_asset"), AnimationAsset->GetPathName());
                Semantic->SetStringField(TEXT("animation_asset_class"),
                    AnimationAsset->GetClass()->GetPathName());
            }
        }
        else if (Cast<UAnimGraphNode_Root>(Node))
        {
            OutOperation = TEXT("anim_graph_root");
        }
        else if (Cast<UAnimGraphNode_TransitionResult>(Node))
        {
            OutOperation = TEXT("anim_transition_result");
        }
        else if (Cast<UAnimGraphNode_StateResult>(Node))
        {
            OutOperation = TEXT("anim_state_result");
        }

        // -----------------------------------------------------------------
        // Generic K2 graph semantics
        // -----------------------------------------------------------------
        else if (UK2Node_FunctionEntry* FunctionEntry = Cast<UK2Node_FunctionEntry>(Node))
        {
            OutOperation = TEXT("function_entry");
            AddMemberReferenceFields(
                FunctionEntry->FunctionReference,
                SelfScope,
                Semantic,
                OutSymbol,
                OutOwner);

            if (UFunction* SignatureFunction = FunctionEntry->FindSignatureFunction())
            {
                OutSymbol = SignatureFunction->GetName();
                if (UClass* OwnerClass = SignatureFunction->GetOwnerClass())
                {
                    OutOwner = OwnerClass->GetPathName();
                }
                Semantic->SetStringField(TEXT("resolved_function"), SignatureFunction->GetPathName());
            }
            Semantic->SetNumberField(TEXT("function_flags"), FunctionEntry->GetFunctionFlags());
            Semantic->SetNumberField(TEXT("local_variable_count"), FunctionEntry->LocalVariables.Num());
            Semantic->SetStringField(TEXT("custom_generated_function_name"),
                FunctionEntry->CustomGeneratedFunctionName.ToString());
        }
        else if (UK2Node_FunctionResult* FunctionResult = Cast<UK2Node_FunctionResult>(Node))
        {
            OutOperation = TEXT("function_result");
            AddMemberReferenceFields(
                FunctionResult->FunctionReference,
                SelfScope,
                Semantic,
                OutSymbol,
                OutOwner);

            if (UFunction* SignatureFunction = FunctionResult->FindSignatureFunction())
            {
                OutSymbol = SignatureFunction->GetName();
                if (UClass* OwnerClass = SignatureFunction->GetOwnerClass())
                {
                    OutOwner = OwnerClass->GetPathName();
                }
                Semantic->SetStringField(TEXT("resolved_function"), SignatureFunction->GetPathName());
            }
        }
        else if (UK2Node_VariableGet* VariableGet = Cast<UK2Node_VariableGet>(Node))
        {
            OutOperation = TEXT("variable_get");
            AddMemberReferenceFields(VariableGet->VariableReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (UClass* SourceClass = VariableGet->GetVariableSourceClass())
            {
                OutOwner = SourceClass->GetPathName();
                Semantic->SetStringField(TEXT("variable_source_class"), OutOwner);
            }
        }
        else if (UK2Node_VariableSet* VariableSet = Cast<UK2Node_VariableSet>(Node))
        {
            OutOperation = TEXT("variable_set");
            AddMemberReferenceFields(VariableSet->VariableReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (UClass* SourceClass = VariableSet->GetVariableSourceClass())
            {
                OutOwner = SourceClass->GetPathName();
                Semantic->SetStringField(TEXT("variable_source_class"), OutOwner);
            }
        }
        else if (UK2Node_CallFunction* Call = Cast<UK2Node_CallFunction>(Node))
        {
            OutOperation = TEXT("function_call");
            AddMemberReferenceFields(Call->FunctionReference, SelfScope, Semantic, OutSymbol, OutOwner);

            // UE 5.8 deprecates bIsPureFunc/bIsConstFunc/bIsInterfaceCall.
            // Query the compiler-facing API and resolved reflection metadata instead.
            Semantic->SetBoolField(TEXT("pure"), Call->IsNodePure());

            UClass* ReferenceOwner = Call->FunctionReference.GetMemberParentClass(SelfScope);
            Semantic->SetBoolField(
                TEXT("interface_call"),
                ReferenceOwner && ReferenceOwner->HasAnyClassFlags(CLASS_Interface));

            if (UFunction* Function = Call->GetTargetFunction())
            {
                OutSymbol = Function->GetName();
                if (UClass* OwnerClass = Function->GetOwnerClass())
                {
                    OutOwner = OwnerClass->GetPathName();
                }
                Semantic->SetStringField(TEXT("resolved_function"), Function->GetPathName());
                Semantic->SetStringField(TEXT("function_name"), OutSymbol);
                Semantic->SetStringField(TEXT("function_owner"), OutOwner);
                Semantic->SetNumberField(TEXT("function_flags"), static_cast<double>(Function->FunctionFlags));
                Semantic->SetBoolField(TEXT("const"), Function->HasAnyFunctionFlags(FUNC_Const));
                Semantic->SetBoolField(TEXT("latent"), Call->IsLatentFunction());
            }
            else
            {
                Semantic->SetBoolField(TEXT("const"), false);
                Semantic->SetBoolField(TEXT("latent"), false);
            }
        }
        else if (UK2Node_CustomEvent* CustomEvent = Cast<UK2Node_CustomEvent>(Node))
        {
            OutOperation = TEXT("custom_event");
            OutSymbol = CustomEvent->CustomFunctionName.ToString();
            if (OutSymbol.IsEmpty())
            {
                AddMemberReferenceFields(CustomEvent->EventReference, SelfScope, Semantic, OutSymbol, OutOwner);
            }
            Semantic->SetStringField(TEXT("event_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("call_in_editor"), CustomEvent->bCallInEditor);
            Semantic->SetBoolField(TEXT("deprecated"), CustomEvent->bIsDeprecated);
            Semantic->SetNumberField(TEXT("function_flags"), static_cast<double>(CustomEvent->FunctionFlags));
        }
        else if (UK2Node_Event* Event = Cast<UK2Node_Event>(Node))
        {
            OutOperation = TEXT("event");
            AddMemberReferenceFields(Event->EventReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (OutSymbol.IsEmpty())
            {
                OutSymbol = Event->CustomFunctionName.ToString();
            }
            Semantic->SetStringField(TEXT("event_name"), OutSymbol);
            Semantic->SetBoolField(TEXT("override_function"), Event->bOverrideFunction);
            Semantic->SetBoolField(TEXT("internal_event"), Event->bInternalEvent);
            Semantic->SetNumberField(TEXT("function_flags"), static_cast<double>(Event->FunctionFlags));
        }
        else if (UK2Node_DynamicCast* DynamicCast = Cast<UK2Node_DynamicCast>(Node))
        {
            OutOperation = TEXT("dynamic_cast");
            if (UClass* TargetClass = DynamicCast->TargetType.Get())
            {
                OutSymbol = TargetClass->GetName();
                OutOwner = TargetClass->GetPathName();
                Semantic->SetStringField(TEXT("target_class"), OutOwner);
            }
        }
        else if (UK2Node_SpawnActorFromClass* SpawnActor = Cast<UK2Node_SpawnActorFromClass>(Node))
        {
            OutOperation = TEXT("spawn_actor");
            if (UClass* SpawnClass = SpawnActor->GetClassToSpawn())
            {
                OutSymbol = SpawnClass->GetName();
                OutOwner = SpawnClass->GetPathName();
                Semantic->SetStringField(TEXT("spawn_class"), OutOwner);
                Semantic->SetBoolField(TEXT("dynamic_class"), false);
            }
            else
            {
                Semantic->SetBoolField(TEXT("dynamic_class"), true);
            }
        }
        else if (UK2Node_MacroInstance* Macro = Cast<UK2Node_MacroInstance>(Node))
        {
            OutOperation = TEXT("macro_instance");
            if (UEdGraph* MacroGraph = Macro->GetMacroGraph())
            {
                OutSymbol = MacroGraph->GetName();
                Semantic->SetStringField(TEXT("macro_graph"), MacroGraph->GetPathName());
            }
            if (UBlueprint* SourceBlueprint = Macro->GetSourceBlueprint())
            {
                OutOwner = SourceBlueprint->GetPathName();
                Semantic->SetStringField(TEXT("source_blueprint"), OutOwner);
            }
        }
        else if (UK2Node_Switch* SwitchNode = Cast<UK2Node_Switch>(Node))
        {
            OutOperation = TEXT("switch");
            OutSymbol = SwitchNode->GetClass()->GetName();
            Semantic->SetBoolField(TEXT("has_default_pin"), SwitchNode->bHasDefaultPin);
            Semantic->SetStringField(TEXT("function_name"), SwitchNode->FunctionName.ToString());
            if (UClass* FunctionOwner = SwitchNode->FunctionClass.Get())
            {
                Semantic->SetStringField(TEXT("function_class"), FunctionOwner->GetPathName());
            }
            if (UEdGraphPin* SelectionPin = SwitchNode->GetSelectionPin())
            {
                Semantic->SetObjectField(TEXT("selection_type"), PinTypeToJson(SelectionPin->PinType));
            }
        }
        else if (UK2Node_Select* Select = Cast<UK2Node_Select>(Node))
        {
            OutOperation = TEXT("select");
            Semantic->SetBoolField(TEXT("pure"), Select->IsNodePure());
        }
        else if (UK2Node_ExecutionSequence* Sequence = Cast<UK2Node_ExecutionSequence>(Node))
        {
            OutOperation = TEXT("execution_sequence");
            int32 OutputExecPins = 0;
            for (const UEdGraphPin* Pin : Sequence->Pins)
            {
                if (Pin && Pin->Direction == EGPD_Output && Pin->PinType.PinCategory == FName(TEXT("exec")))
                {
                    ++OutputExecPins;
                }
            }
            Semantic->SetNumberField(TEXT("output_exec_pins"), OutputExecPins);
        }
        else if (Cast<UK2Node_Knot>(Node))
        {
            OutOperation = TEXT("reroute");
        }
        else if (Cast<UK2Node_IfThenElse>(Node))
        {
            OutOperation = TEXT("branch");
        }
        else if (Cast<UK2Node_Tunnel>(Node))
        {
            OutOperation = TEXT("tunnel");
        }
        else if (Cast<UK2Node_Self>(Node))
        {
            OutOperation = TEXT("self");
            OutSymbol = TEXT("self");
            OutOwner = SelfScope ? SelfScope->GetPathName() : TEXT("");
        }
        else if (UEdGraphNode_Comment* Comment = Cast<UEdGraphNode_Comment>(Node))
        {
            OutOperation = TEXT("comment");
            OutSymbol = Comment->NodeComment;
            Semantic->SetStringField(TEXT("details"), Comment->NodeDetails.ToString());
            Semantic->SetNumberField(TEXT("font_size"), Comment->FontSize);
        }
        else if (UK2Node_Variable* Variable = Cast<UK2Node_Variable>(Node))
        {
            OutOperation = TEXT("variable_reference");
            AddMemberReferenceFields(Variable->VariableReference, SelfScope, Semantic, OutSymbol, OutOwner);
            if (UClass* SourceClass = Variable->GetVariableSourceClass())
            {
                OutOwner = SourceClass->GetPathName();
                Semantic->SetStringField(TEXT("variable_source_class"), OutOwner);
            }
        }

        ApplyClassSemanticFallback(Node, Semantic, OutOperation, OutSymbol, OutOwner);
        ApplyReflectedSemanticEnrichment(Blueprint, Node, Semantic, OutOperation, OutSymbol, OutOwner);

        Semantic->SetStringField(TEXT("operation"), OutOperation);
        Semantic->SetStringField(TEXT("symbol"), OutSymbol);
        Semantic->SetStringField(TEXT("owner"), OutOwner);
        return Semantic;
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


    static FString ExportStructFieldText(
        FStructProperty* StructProperty,
        void* StructValue,
        UObject* Owner,
        const FName FieldName)
    {
        if (!StructProperty || !StructProperty->Struct || !StructValue)
        {
            return TEXT("");
        }

        FProperty* Field = StructProperty->Struct->FindPropertyByName(FieldName);
        if (!Field)
        {
            return TEXT("");
        }

        const void* FieldValue = Field->ContainerPtrToValuePtr<void>(StructValue);
        FString Result;
        Field->ExportTextItem_Direct(
            Result,
            FieldValue,
            nullptr,
            Owner,
            PPF_None,
            nullptr);
        return Result;
    }

    static TArray<FString> ExportStructArrayFieldTexts(
        FStructProperty* StructProperty,
        void* StructValue,
        UObject* Owner,
        const FName FieldName)
    {
        TArray<FString> Result;
        if (!StructProperty || !StructProperty->Struct || !StructValue)
        {
            return Result;
        }

        FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
            StructProperty->Struct->FindPropertyByName(FieldName));
        if (!ArrayProperty || !ArrayProperty->Inner)
        {
            return Result;
        }

        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(StructValue);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        Result.Reserve(Helper.Num());

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            FString Value;
            ArrayProperty->Inner->ExportTextItem_Direct(
                Value,
                Helper.GetRawPtr(Index),
                nullptr,
                Owner,
                PPF_None,
                nullptr);
            Result.Add(MoveTemp(Value));
        }
        return Result;
    }

    static bool ScanNodeBindings(
        UEdGraphNode* Node,
        const FString& NodeId,
        const FString& BlueprintPath,
        const FString& GraphName,
        FJsonlWriter& BindingsWriter,
        FScanCounts& Counts)
    {
        if (!Node)
        {
            return true;
        }

        UObject* BindingObject = GetReflectedObjectProperty(Node, TEXT("Binding"));
        if (!BindingObject)
        {
            return true;
        }

        FMapProperty* BindingsProperty = CastField<FMapProperty>(
            BindingObject->GetClass()->FindPropertyByName(TEXT("PropertyBindings")));
        if (!BindingsProperty || !BindingsProperty->KeyProp || !BindingsProperty->ValueProp)
        {
            return true;
        }

        FStructProperty* ValueStructProperty = CastField<FStructProperty>(BindingsProperty->ValueProp);
        if (!ValueStructProperty || !ValueStructProperty->Struct)
        {
            return true;
        }

        void* MapValue = BindingsProperty->ContainerPtrToValuePtr<void>(BindingObject);
        FScriptMapHelper Helper(BindingsProperty, MapValue);

        for (int32 Index = 0; Index < Helper.GetMaxIndex(); ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }

            void* KeyPtr = Helper.GetKeyPtr(Index);
            void* ValuePtr = Helper.GetValuePtr(Index);

            FString KeyText;
            BindingsProperty->KeyProp->ExportTextItem_Direct(
                KeyText,
                KeyPtr,
                nullptr,
                BindingObject,
                PPF_None,
                nullptr);

            FString RawValue;
            BindingsProperty->ValueProp->ExportTextItem_Direct(
                RawValue,
                ValuePtr,
                nullptr,
                BindingObject,
                PPF_None,
                nullptr);

            const FString PropertyName = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PropertyName"));
            const FString PathAsText = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PathAsText"));
            const FString CompiledContext = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("CompiledContext"));
            const FString PinType = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PinType"));
            const FString PromotedPinType = ExportStructFieldText(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PromotedPinType"));
            const TArray<FString> PropertyPath = ExportStructArrayFieldTexts(
                ValueStructProperty, ValuePtr, BindingObject, TEXT("PropertyPath"));

            TArray<TSharedPtr<FJsonValue>> PathJson;
            PathJson.Reserve(PropertyPath.Num());
            for (const FString& Segment : PropertyPath)
            {
                PathJson.Add(MakeShared<FJsonValueString>(Segment));
            }

            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("node_id"), NodeId);
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetStringField(TEXT("graph_name"), GraphName);
            Json->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
            Json->SetStringField(TEXT("binding_object"), BindingObject->GetPathName());
            Json->SetStringField(TEXT("binding_key"), KeyText);
            Json->SetStringField(TEXT("target_property"), PropertyName.IsEmpty() ? KeyText : PropertyName);
            Json->SetStringField(TEXT("access_path"), PathAsText);
            Json->SetArrayField(TEXT("property_path"), PathJson);
            Json->SetStringField(TEXT("compiled_context"), CompiledContext);
            Json->SetStringField(TEXT("pin_type"), PinType);
            Json->SetStringField(TEXT("promoted_pin_type"), PromotedPinType);
            Json->SetStringField(TEXT("raw_value"), RawValue);

            if (!BindingsWriter.Write(Json))
            {
                return false;
            }
            ++Counts.BlueprintBindings;
        }

        return true;
    }

    static bool ClassIsOrDerivedFromName(const UClass* Class, const FName BaseClassName)
    {
        for (const UClass* Current = Class; Current; Current = Current->GetSuperClass())
        {
            if (Current->GetFName() == BaseClassName)
            {
                return true;
            }
        }
        return false;
    }

    static FString RigVMObjectKind(UObject* Object)
    {
        if (!Object)
        {
            return TEXT("");
        }

        UClass* Class = Object->GetClass();
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMGraph"))) return TEXT("graph");
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMNode"))) return TEXT("node");
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMPin"))) return TEXT("pin");
        if (ClassIsOrDerivedFromName(Class, TEXT("RigVMLink"))) return TEXT("link");
        return TEXT("");
    }

    static FString RigVMNodeOperation(UObject* Object)
    {
        if (!Object || !ClassIsOrDerivedFromName(Object->GetClass(), TEXT("RigVMNode")))
        {
            return TEXT("");
        }

        struct FRigVMClassSemantic
        {
            const TCHAR* ClassName;
            const TCHAR* Operation;
        };

        static const FRigVMClassSemantic Classes[] =
        {
            { TEXT("RigVMFunctionEntryNode"), TEXT("rigvm_function_entry") },
            { TEXT("RigVMFunctionReturnNode"), TEXT("rigvm_function_return") },
            { TEXT("RigVMFunctionReferenceNode"), TEXT("rigvm_function_reference") },
            { TEXT("RigVMVariableNode"), TEXT("rigvm_variable") },
            { TEXT("RigVMUnitNode"), TEXT("rigvm_unit") },
            { TEXT("RigVMDispatchNode"), TEXT("rigvm_dispatch") },
            { TEXT("RigVMInvokeEntryNode"), TEXT("rigvm_invoke_entry") },
            { TEXT("RigVMRerouteNode"), TEXT("rigvm_reroute") },
            { TEXT("RigVMEnumNode"), TEXT("rigvm_enum") },
            { TEXT("RigVMCommentNode"), TEXT("rigvm_comment") },
            { TEXT("RigVMParameterNode"), TEXT("rigvm_parameter") },
            { TEXT("RigVMLibraryNode"), TEXT("rigvm_library") },
            { TEXT("RigVMTemplateNode"), TEXT("rigvm_template") }
        };

        for (const FRigVMClassSemantic& Entry : Classes)
        {
            if (ClassIsOrDerivedFromName(Object->GetClass(), FName(Entry.ClassName)))
            {
                return Entry.Operation;
            }
        }
        return TEXT("rigvm_node");
    }

    static bool WriteRigVMReference(
        UObject* SourceObject,
        UObject* TargetObject,
        const FString& BlueprintPath,
        const FString& PropertyPath,
        FJsonlWriter& ReferencesWriter,
        FScanCounts& Counts)
    {
        if (!SourceObject || !TargetObject)
        {
            return true;
        }

        const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("source_object_id"), SourceObject->GetPathName());
        Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
        Json->SetStringField(TEXT("source_kind"), RigVMObjectKind(SourceObject));
        Json->SetStringField(TEXT("source_class"), SourceObject->GetClass()->GetPathName());
        Json->SetStringField(TEXT("property_path"), PropertyPath);
        Json->SetStringField(TEXT("target_object_id"), TargetObject->GetPathName());
        Json->SetStringField(TEXT("target_kind"), RigVMObjectKind(TargetObject));
        Json->SetStringField(TEXT("target_class"), TargetObject->GetClass()->GetPathName());

        if (!ReferencesWriter.Write(Json))
        {
            return false;
        }
        ++Counts.RigVMReferences;
        return true;
    }

    static bool ScanRigVMObjectProperties(
        UObject* Object,
        const FString& BlueprintPath,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FScanCounts& Counts)
    {
        if (!Object)
        {
            return true;
        }

        static constexpr int32 MaxExportedPropertyChars = 65536;
        const FString Kind = RigVMObjectKind(Object);

        for (UClass* Class = Object->GetClass();
             Class && Class != UObject::StaticClass();
             Class = Class->GetSuperClass())
        {
            for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
            {
                FProperty* Property = *It;
                if (!IsCapturableProperty(Property))
                {
                    continue;
                }

                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
                FString Value;
                Property->ExportTextItem_Direct(
                    Value,
                    ValuePtr,
                    nullptr,
                    Object,
                    PPF_None,
                    nullptr);

                bool bTruncated = false;
                if (Value.Len() > MaxExportedPropertyChars)
                {
                    Value = Value.Left(MaxExportedPropertyChars);
                    bTruncated = true;
                }

                FString ObjectPath;
                FString ObjectClass;
                UObject* ObjectValue = nullptr;
                if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
                {
                    ObjectValue = ObjectProperty->GetObjectPropertyValue(ValuePtr);
                    if (ObjectValue)
                    {
                        ObjectPath = ObjectValue->GetPathName();
                        ObjectClass = ObjectValue->GetClass()->GetPathName();
                    }
                }

                const TSharedRef<FJsonObject> PropertyJson = MakeShared<FJsonObject>();
                PropertyJson->SetStringField(TEXT("object_id"), Object->GetPathName());
                PropertyJson->SetStringField(TEXT("blueprint_path"), BlueprintPath);
                PropertyJson->SetStringField(TEXT("kind"), Kind);
                PropertyJson->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
                PropertyJson->SetStringField(TEXT("declaring_type"), Class->GetPathName());
                PropertyJson->SetStringField(TEXT("property_name"), Property->GetName());
                PropertyJson->SetStringField(TEXT("property_path"), Property->GetName());
                PropertyJson->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                PropertyJson->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                PropertyJson->SetStringField(TEXT("value"), Value);
                PropertyJson->SetStringField(TEXT("object_path"), ObjectPath);
                PropertyJson->SetStringField(TEXT("object_class"), ObjectClass);
                PropertyJson->SetNumberField(TEXT("property_flags"), static_cast<double>(Property->GetPropertyFlags()));
                PropertyJson->SetBoolField(TEXT("truncated"), bTruncated);

                if (!PropertiesWriter.Write(PropertyJson))
                {
                    return false;
                }
                ++Counts.RigVMProperties;

                if (ObjectValue)
                {
                    if (!WriteRigVMReference(
                            Object,
                            ObjectValue,
                            BlueprintPath,
                            Property->GetName(),
                            ReferencesWriter,
                            Counts))
                    {
                        return false;
                    }
                }

                if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
                {
                    FObjectPropertyBase* InnerObjectProperty = CastField<FObjectPropertyBase>(ArrayProperty->Inner);
                    if (!InnerObjectProperty)
                    {
                        continue;
                    }

                    FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
                    for (int32 Index = 0; Index < Helper.Num(); ++Index)
                    {
                        UObject* ElementObject = InnerObjectProperty->GetObjectPropertyValue(Helper.GetRawPtr(Index));
                        if (!ElementObject)
                        {
                            continue;
                        }

                        const FString ElementPath = FString::Printf(
                            TEXT("%s[%d]"),
                            *Property->GetName(),
                            Index);
                        if (!WriteRigVMReference(
                                Object,
                                ElementObject,
                                BlueprintPath,
                                ElementPath,
                                ReferencesWriter,
                                Counts))
                        {
                            return false;
                        }
                    }
                }
            }
        }

        return true;
    }

    static bool ScanRigVMObjects(
        UBlueprint* Blueprint,
        const FString& BlueprintPath,
        FJsonlWriter& ObjectsWriter,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FScanCounts& Counts)
    {
        if (!Blueprint)
        {
            return true;
        }

        TArray<UObject*> OwnedObjects;
        GetObjectsWithOuter(Blueprint, OwnedObjects, true);

        for (UObject* Object : OwnedObjects)
        {
            const FString Kind = RigVMObjectKind(Object);
            if (Kind.IsEmpty())
            {
                continue;
            }

            const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
            Json->SetStringField(TEXT("object_id"), Object->GetPathName());
            Json->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            Json->SetStringField(TEXT("kind"), Kind);
            Json->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
            Json->SetStringField(TEXT("name"), Object->GetName());
            Json->SetStringField(TEXT("outer_object_id"), Object->GetOuter() ? Object->GetOuter()->GetPathName() : TEXT(""));
            Json->SetStringField(TEXT("outer_class"), Object->GetOuter() ? Object->GetOuter()->GetClass()->GetPathName() : TEXT(""));
            Json->SetStringField(TEXT("operation"), Kind == TEXT("node") ? RigVMNodeOperation(Object) : TEXT(""));

            if (!ObjectsWriter.Write(Json))
            {
                return false;
            }
            ++Counts.RigVMObjects;

            if (!ScanRigVMObjectProperties(
                    Object,
                    BlueprintPath,
                    PropertiesWriter,
                    ReferencesWriter,
                    Counts))
            {
                return false;
            }
        }

        return true;
    }

    static bool ScanBlueprint(
        UBlueprint* Blueprint,
        const FString& ObjectPath,
        FJsonlWriter& BlueprintsWriter,
        FJsonlWriter& NodesWriter,
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FJsonlWriter& BindingsWriter,
        FJsonlWriter& RigVMObjectsWriter,
        FJsonlWriter& RigVMPropertiesWriter,
        FJsonlWriter& RigVMReferencesWriter,
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

                FString Operation;
                FString Symbol;
                FString Owner;
                const TSharedRef<FJsonObject> Semantic = BuildNodeSemantic(Blueprint, Node, Operation, Symbol, Owner);
                NodeJson->SetStringField(TEXT("operation"), Operation);
                NodeJson->SetStringField(TEXT("symbol"), Symbol);
                NodeJson->SetStringField(TEXT("owner"), Owner);
                NodeJson->SetObjectField(TEXT("semantic"), Semantic);
                if (Operation != TEXT("node"))
                {
                    ++Counts.BlueprintSemanticNodes;
                }

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

                if (!ScanNodeProperties(
                        Node,
                        NodeId,
                        ObjectPath,
                        Graph->GetName(),
                        PropertiesWriter,
                        ReferencesWriter,
                        Counts))
                {
                    return false;
                }

                if (!ScanNodeBindings(
                        Node,
                        NodeId,
                        ObjectPath,
                        Graph->GetName(),
                        BindingsWriter,
                        Counts))
                {
                    return false;
                }
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

        if (!ScanRigVMObjects(
                Blueprint,
                ObjectPath,
                RigVMObjectsWriter,
                RigVMPropertiesWriter,
                RigVMReferencesWriter,
                Counts))
        {
            return false;
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
        FJsonlWriter& PropertiesWriter,
        FJsonlWriter& ReferencesWriter,
        FJsonlWriter& BindingsWriter,
        FJsonlWriter& RigVMObjectsWriter,
        FJsonlWriter& RigVMPropertiesWriter,
        FJsonlWriter& RigVMReferencesWriter,
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
                    if (!ScanBlueprint(
                            Blueprint,
                            ObjectPath,
                            BlueprintsWriter,
                            NodesWriter,
                            PropertiesWriter,
                            ReferencesWriter,
                            BindingsWriter,
                            RigVMObjectsWriter,
                            RigVMPropertiesWriter,
                            RigVMReferencesWriter,
                            EdgesWriter,
                            Counts))
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
    FJsonlWriter PropertiesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_node_properties.jsonl")));
    FJsonlWriter ReferencesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_node_references.jsonl")));
    FJsonlWriter BindingsWriter(FPaths::Combine(OutputDir, TEXT("blueprint_bindings.jsonl")));
    FJsonlWriter RigVMObjectsWriter(FPaths::Combine(OutputDir, TEXT("rigvm_objects.jsonl")));
    FJsonlWriter RigVMPropertiesWriter(FPaths::Combine(OutputDir, TEXT("rigvm_properties.jsonl")));
    FJsonlWriter RigVMReferencesWriter(FPaths::Combine(OutputDir, TEXT("rigvm_references.jsonl")));
    FJsonlWriter EdgesWriter(FPaths::Combine(OutputDir, TEXT("blueprint_edges.jsonl")));

    if (!FilesWriter.IsValid() || !SourceWriter.IsValid() || !AssetsWriter.IsValid() ||
        !DependenciesWriter.IsValid() || !BlueprintsWriter.IsValid() || !NodesWriter.IsValid() ||
        !PropertiesWriter.IsValid() || !ReferencesWriter.IsValid() || !BindingsWriter.IsValid() ||
        !RigVMObjectsWriter.IsValid() || !RigVMPropertiesWriter.IsValid() || !RigVMReferencesWriter.IsValid() ||
        !EdgesWriter.IsValid())
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

    if (!ScanAssets(
            ProjectDir,
            ToolPluginDir,
            bIncludeEngine,
            bIncludeSelf,
            AssetsWriter,
            DependenciesWriter,
            BlueprintsWriter,
            NodesWriter,
            PropertiesWriter,
            ReferencesWriter,
            BindingsWriter,
            RigVMObjectsWriter,
            RigVMPropertiesWriter,
            RigVMReferencesWriter,
            EdgesWriter,
            Counts))
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
    CountsJson->SetNumberField(TEXT("blueprint_semantic_nodes"), static_cast<double>(Counts.BlueprintSemanticNodes));
    CountsJson->SetNumberField(TEXT("blueprint_node_properties"), static_cast<double>(Counts.BlueprintNodeProperties));
    CountsJson->SetNumberField(TEXT("blueprint_node_references"), static_cast<double>(Counts.BlueprintNodeReferences));
    CountsJson->SetNumberField(TEXT("blueprint_bindings"), static_cast<double>(Counts.BlueprintBindings));
    CountsJson->SetNumberField(TEXT("rigvm_objects"), static_cast<double>(Counts.RigVMObjects));
    CountsJson->SetNumberField(TEXT("rigvm_properties"), static_cast<double>(Counts.RigVMProperties));
    CountsJson->SetNumberField(TEXT("rigvm_references"), static_cast<double>(Counts.RigVMReferences));
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

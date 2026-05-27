using System;
using GLTFast;
using UnityEngine;

public class SafeGameObjectInstantiator : GameObjectInstantiator
{
    public SafeGameObjectInstantiator(
        IGltfReadable gltf,
        Transform parent,
        InstantiationSettings settings = null
    ) : base(gltf, parent, null, settings) { }

    public override void AddPrimitive(
        uint nodeIndex,
        string meshName,
        MeshResult meshResult,
        uint[] joints = null,
        uint? rootJoint = null,
        float[] morphTargetWeights = null,
        int meshNumeration = 0
    )
    {
        if (morphTargetWeights != null)
        {
            int blendShapeCount = meshResult.mesh != null ? meshResult.mesh.blendShapeCount : 0;
            if (blendShapeCount == 0)
            {
                morphTargetWeights = null;
            }
            else if (morphTargetWeights.Length > blendShapeCount)
            {
                var trimmed = new float[blendShapeCount];
                Array.Copy(morphTargetWeights, trimmed, blendShapeCount);
                morphTargetWeights = trimmed;
            }
        }

        base.AddPrimitive(
            nodeIndex,
            meshName,
            meshResult,
            joints,
            rootJoint,
            morphTargetWeights,
            meshNumeration
        );
    }
}

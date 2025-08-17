# Legacy Code Removal Plan

## Progress Summary

### Phase 1: Inventory and Analysis (Completed ✅)
- ✅ Created complete inventory of legacy code
- ✅ Identified test dependencies on legacy code
- ✅ Documented all legacy adapters

### Phase 2: Adapter Removal (Completed ✅)
- ✅ Removed legacy config adapter
- ✅ Removed legacy session adapter
- ✅ Removed legacy command adapter
- ✅ Removed legacy backend adapter

### Phase 3: Integration Bridge Cleanup (In Progress 🔄)
- 🔄 Clean up integration bridge
- ⏳ Fix hybrid controllers
- ⏳ Update test fixtures

### Phase 4: Test Suite Updates (Pending ⏳)
- ⏳ Fix broken tests
- ⏳ Add missing tests
- ⏳ Create integration test suite

### Phase 5: Documentation and Verification (Pending ⏳)
- ⏳ Update all documentation
- ⏳ Improve code quality
- ⏳ Final verification

## Next Steps

1. **Integration Bridge Cleanup**: Remove legacy initialization methods from the integration bridge
2. **Hybrid Controller Cleanup**: Remove legacy flow methods from the hybrid controller
3. **Test Fixture Updates**: Update test fixtures to use the new architecture components directly
4. **Test Suite Updates**: Fix broken tests and add missing tests
5. **Documentation Updates**: Update all documentation to reflect the new architecture
6. **Final Verification**: Verify that all functionality is preserved with no regressions

## Remaining Legacy Components

1. **Integration Bridge**:
   - `initialize_legacy_architecture()`
   - `_setup_legacy_backends()`
   - `_setup_legacy_backends_sync()`
   - `ensure_legacy_state()`

2. **Hybrid Controller**:
   - `_hybrid_legacy_flow_with_new_services()`

3. **Legacy State Compatibility**:
   - `src/core/app/legacy_state_compatibility.py`

4. **Session Migration Service**:
   - `migrate_legacy_session()`
   - `sync_session_state()`
   - `create_hybrid_session()`

5. **Domain Model Compatibility Methods**:
   - `to_legacy_format()`
   - `from_legacy_response()`
   - `from_legacy_chunk()`
   - `from_legacy_message()`

## Timeline

1. **Day 1**: Clean up integration bridge (in progress)
2. **Day 2**: Fix hybrid controllers
3. **Day 3**: Update test fixtures
4. **Day 4**: Fix broken tests
5. **Day 5**: Add missing tests
6. **Day 6**: Update documentation
7. **Day 7**: Final verification

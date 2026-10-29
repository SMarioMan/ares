find_package(SDL REQUIRED)
add_executable(ares-link-worker worker.cpp)
target_compile_definitions(ares-link-worker PRIVATE MIA_LIBRARY)
target_include_directories(ares-link-worker PRIVATE ${CMAKE_SOURCE_DIR} ${CMAKE_SOURCE_DIR}/ares)
target_link_libraries(ares-link-worker PRIVATE ares::mia ares::ares ares::nall libco SDL::SDL)
add_custom_command(
  TARGET ares-link-worker POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory
    "${CMAKE_SOURCE_DIR}/mia/Database" "$<TARGET_FILE_DIR:ares-link-worker>/Database"
  COMMENT "Stage the ROM and board databases beside the link worker"
)

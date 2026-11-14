cmake_minimum_required(VERSION 3.16)
project(GongchuangClient LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
find_package(Qt6 REQUIRED COMPONENTS Widgets Network)
add_executable(GongchuangClient WIN32 main.cpp)
target_link_libraries(GongchuangClient PRIVATE Qt6::Widgets Qt6::Network)

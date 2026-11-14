"""
这个是最外层封装好的，直到抓取，对外只要用grab就行，然后才是转运

整个流程是 search--track--check--grab
check之后可能还会需要打散，scatter，直到check成功才会grab，否则二者重复，或者目标丢失。
scatter次数最多三次，否则一直前进打散会走的很偏
整个check失败就回退到search



"""
